"""Small Windows UI; analysis and operations run in a separate process."""
import queue
import os
import subprocess
import sys
import threading
import time
import uuid
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from sorter import load_apply_plan

ROOT=Path(__file__).resolve().parent
for key,subdir in [('TCL_LIBRARY','tcl8.6'),('TK_LIBRARY','tk8.6')]:
    library=Path(sys.base_prefix)/'tcl'/subdir
    if library.is_dir(): os.environ.setdefault(key,str(library))

class LogBuffer:
    """Never let decoder chatter or a large batch consume unbounded UI memory."""
    def __init__(self): self.queue=queue.Queue(maxsize=1000); self.dropped=0
    def put(self,line):
        line=line[:4000]
        try: self.queue.put_nowait(line)
        except queue.Full:
            try: self.queue.get_nowait(); self.dropped+=1
            except queue.Empty: pass
            try: self.queue.put_nowait(line)
            except queue.Full: self.dropped+=1
    def drain(self):
        lines=[]; started=time.monotonic()
        for _ in range(100):
            if time.monotonic()-started>.01: break
            try: lines.append(self.queue.get_nowait())
            except queue.Empty: break
        return ''.join(lines)

class App:
    def __init__(self,root):
        self.root=root; root.title('Valorant Clip Sorter'); root.geometry('980x740')
        self.process=None; self.messages=LogBuffer()
        self.checked_selection=None; self.checking=False; self.plan_checks=queue.Queue(); self.was_running=False
        self.folder=tk.StringVar(value=str(ROOT/'sample_clips'))
        self.output=tk.StringVar(value=str(ROOT/'Sorted'))
        self.work=tk.StringVar(value=str(ROOT/'sort_results'))
        self.recursive=tk.BooleanVar()
        self.feed=tk.BooleanVar(value=False); self.retry=tk.BooleanVar(value=False)
        self.timeout=tk.StringVar(value='120')
        form=ttk.Frame(root,padding=12); form.pack(fill='x')
        for i,(label,var) in enumerate([('Clips folder',self.folder),('Sorted output',self.output),('Results / resume folder',self.work)]):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',padx=4,pady=5)
            ttk.Entry(form,textvariable=var,width=90).grid(row=i,column=1,sticky='ew')
            ttk.Button(form,text='Browse',command=lambda v=var:self.browse(v)).grid(row=i,column=2,padx=5)
        form.columnconfigure(1,weight=1)
        ttk.Checkbutton(form,text='Include subfolders',variable=self.recursive).grid(row=3,column=1,sticky='w')
        ttk.Checkbutton(form,text='Collect kill-feed evidence for uncertain clips (slower)',variable=self.feed).grid(row=4,column=1,sticky='w')
        ttk.Checkbutton(form,text='Retry previous decoder errors / timeouts',variable=self.retry).grid(row=5,column=1,sticky='w')
        ttk.Label(form,text='Seconds per clip limit').grid(row=6,column=0,sticky='w')
        ttk.Entry(form,textvariable=self.timeout,width=10).grid(row=6,column=1,sticky='w')
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
        (ROOT/'.tmp').mkdir(exist_ok=True)
        self.cancel_file=ROOT/'.tmp'/f'cancel-{uuid.uuid4().hex}'
        self.process=subprocess.Popen([sys.executable,'-u',str(ROOT/'sorter.py')]+args+['--cancel-file',str(self.cancel_file)],cwd=ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,
            env=__import__('os').environ|{'PYTHONIOENCODING':'utf-8'})
        process=self.process; cancel_file=self.cancel_file
        def collect():
            for line in process.stdout: self.messages.put(line)
            process.wait(); self.messages.put(f'\nProcess finished (exit {process.returncode}).\n')
            cancel_file.unlink(missing_ok=True)
        threading.Thread(target=collect,daemon=True).start()
    def preview(self):
        args=['preview','--input',self.folder.get(),'--output',self.output.get(),'--work',self.work.get()]
        if self.recursive.get(): args+=['--recursive']
        if not self.feed.get(): args+=['--skip-feed']
        if self.retry.get(): args+=['--retry-errors']
        args+=['--clip-timeout',self.timeout.get()]
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
            self.cancel_file.touch()
            self.messages.put('Stopping after a safe checkpoint. Completed clips will resume next time.\n')
    def poll(self):
        batch=self.messages.drain()
        if batch:
            self.log.insert('end',batch)
            lines=int(self.log.index('end-1c').split('.')[0])
            if lines>1500: self.log.delete('1.0',f'{lines-1500}.0')
            self.log.see('end')
        running=self.process is not None and self.process.poll() is None
        if running:
            self.plan_status.set('Working. Progress appears below; Stop preserves completed results.')
        else:
            for b in self.buttons:b.configure(state='normal')
            selection=(self.work.get(),self.folder.get(),self.output.get(),self.recursive.get())
            if self.was_running: self.checked_selection=None
            while not self.plan_checks.empty():
                key,plan,error=self.plan_checks.get_nowait(); self.checking=False
                if key==selection:
                    self.checked_selection=key
                    self.plan_status.set(error or f'Ready to apply saved preview: {plan["input"]} → {plan["output"]}')
                    self.plan_valid=not error
            if self.checked_selection!=selection:
                self.plan_valid=False
                self.plan_status.set('Checking saved preview for these folders...')
                if not self.checking:
                    self.checking=True
                    def check(key):
                        try: self.plan_checks.put((key,load_apply_plan(*key),None))
                        except (OSError,ValueError,RuntimeError) as e: self.plan_checks.put((key,None,str(e)))
                    threading.Thread(target=check,args=(selection,),daemon=True).start()
            if not getattr(self,'plan_valid',False):
                for b in self.buttons[1:3]:b.configure(state='disabled')
        self.was_running=running
        self.root.after(100,self.poll)
    def close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno('Stop current action','Stop and close? The same command can recover and resume.'): return
            self.stop()
        self.root.destroy()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
