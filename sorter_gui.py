"""Small Windows UI; analysis and operations run in a separate process."""
import queue
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from sorter import load_apply_plan

ROOT=Path(__file__).resolve().parent
for key,subdir in [('TCL_LIBRARY','tcl8.6'),('TK_LIBRARY','tk8.6')]:
    library=Path(sys.base_prefix)/'tcl'/subdir
    if library.is_dir(): os.environ.setdefault(key,str(library))

class App:
    def __init__(self,root):
        self.root=root; root.title('Valorant Clip Sorter'); root.geometry('940x640')
        self.process=None; self.messages=queue.Queue()
        self.folder=tk.StringVar(value=str(ROOT/'sample_clips'))
        self.output=tk.StringVar(value=str(ROOT/'Sorted'))
        self.work=tk.StringVar(value=str(ROOT/'sort_results'))
        self.recursive=tk.BooleanVar()
        form=ttk.Frame(root,padding=12); form.pack(fill='x')
        for i,(label,var) in enumerate([('Clips folder',self.folder),('Sorted output',self.output),('Results / resume folder',self.work)]):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',padx=4,pady=5)
            ttk.Entry(form,textvariable=var,width=90).grid(row=i,column=1,sticky='ew')
            ttk.Button(form,text='Browse',command=lambda v=var:self.browse(v)).grid(row=i,column=2,padx=5)
        form.columnconfigure(1,weight=1)
        ttk.Checkbutton(form,text='Include subfolders',variable=self.recursive).grid(row=3,column=1,sticky='w')
        ttk.Label(root,text='1. Choose folders   2. Preview / Resume   3. Review results   4. Copy or Move',padding=8).pack(anchor='w')
        self.plan_status=tk.StringVar()
        ttk.Label(root,textvariable=self.plan_status,padding=8,wraplength=900).pack(anchor='w')
        actions=ttk.Frame(root,padding=8); actions.pack(fill='x')
        self.buttons=[]
        for label,cmd in [('Preview / Resume',self.preview),('Copy from preview',lambda:self.apply('copy')),
                          ('Move from preview',lambda:self.apply('move')),('Undo',self.undo),('Open results',self.open_results)]:
            b=ttk.Button(actions,text=label,command=cmd); b.pack(side='left',padx=3); self.buttons.append(b)
        ttk.Button(actions,text='Stop',command=self.stop).pack(side='left',padx=3)
        self.log=tk.Text(root,wrap='word'); self.log.pack(fill='both',expand=True,padx=12,pady=8)
        self.log.insert('end','Your account aliases are configured. Hidden agent names do not affect combat-report counting.\n')
        root.protocol('WM_DELETE_WINDOW',self.close); root.after(100,self.poll)
    def browse(self,var):
        path=filedialog.askdirectory(initialdir=var.get())
        if path: var.set(path)
    def run(self,args):
        if self.process and self.process.poll() is None: return
        for b in self.buttons: b.configure(state='disabled')
        self.process=subprocess.Popen([sys.executable,'-u',str(ROOT/'sorter.py')]+args,cwd=ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,
            env=__import__('os').environ|{'PYTHONIOENCODING':'utf-8'})
        process=self.process
        def collect():
            for line in process.stdout: self.messages.put(line)
            process.wait(); self.messages.put(f'\nProcess finished (exit {process.returncode}).\n')
        threading.Thread(target=collect,daemon=True).start()
    def preview(self):
        args=['preview','--input',self.folder.get(),'--output',self.output.get(),'--work',self.work.get()]
        if self.recursive.get(): args+=['--recursive']
        self.run(args)
    def apply(self,mode):
        try: plan=load_apply_plan(self.work.get(),self.folder.get(),self.output.get(),self.recursive.get())
        except (OSError,ValueError,RuntimeError) as e:
            messagebox.showerror('Preview required',str(e)); return
        if mode=='move' and not messagebox.askyesno('Move clips',f'Move the clips from this saved preview?\n\nFrom: {plan["input"]}\nTo: {plan["output"]}\n\nOriginals are removed after verified copies are saved.'): return
        self.run(['apply','--work',self.work.get(),'--mode',mode,
                  '--expected-input',self.folder.get(),'--expected-output',self.output.get(),
                  '--expected-recursive',str(self.recursive.get()).lower()])
    def undo(self):
        if messagebox.askyesno('Undo','Undo saved copy/move operations? Changed files and occupied original paths will be refused.'):
            self.run(['undo','--work',self.work.get()])
    def open_results(self):
        import os
        folder=Path(self.work.get()).resolve(); folder.mkdir(parents=True,exist_ok=True); os.startfile(folder)
    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate(); self.messages.put('Stopped. Rerun the same action to recover and resume.\n')
    def poll(self):
        while not self.messages.empty(): self.log.insert('end',self.messages.get()); self.log.see('end')
        if not self.process or self.process.poll() is not None:
            for b in self.buttons:b.configure(state='normal')
            try:
                plan=load_apply_plan(self.work.get(),self.folder.get(),self.output.get(),self.recursive.get())
                self.plan_status.set(f'Ready to apply saved preview: {plan["input"]} → {plan["output"]}')
            except (OSError,ValueError,RuntimeError) as e:
                self.plan_status.set(str(e))
                for b in self.buttons[1:3]: b.configure(state='disabled')
        self.root.after(100,self.poll)
    def close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno('Stop current action','Stop and close? The same command can recover and resume.'): return
            self.stop()
        self.root.destroy()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
