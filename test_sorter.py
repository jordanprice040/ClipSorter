import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sorter

class Operations(unittest.TestCase):
    def setUp(self):
        Path('.tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=Path('.tmp').resolve())
        self.root=Path(self.temp.name); self.src=self.root/'input'; self.src.mkdir()
        self.output=self.root/'sorted'; self.state=sorter.State(self.root/'work')
        sorter.atomic_json(self.state.work/'plan.json',dict(output=str(self.output),complete=True))
        self.file=self.src/'clip.mp4'; self.file.write_bytes(b'disposable test clip\0'*1000)
        self.sha=sorter.digest(self.file)
        self.state.db.execute('INSERT INTO clips VALUES (?,?,?,?,1)',(str(self.file),'sig',self.sha,json.dumps(dict(category='2')))); self.state.db.commit()
    def tearDown(self): self.state.close(); self.temp.cleanup()
    def apply(self,mode='copy'): sorter.apply(argparse.Namespace(mode=mode),self.state)
    def undo(self): sorter.undo(argparse.Namespace(),self.state)
    def test_copy_collision_resume_and_undo(self):
        category=self.output/'2'; category.mkdir(parents=True)
        existing=category/self.file.name; existing.write_bytes(b'keep me')
        self.apply(); self.apply()
        copied=category/'clip (1).mp4'
        self.assertEqual(sorter.digest(copied),self.sha)
        self.assertEqual(len(list(category.iterdir())),2)
        self.undo(); self.undo()
        self.assertTrue(self.file.exists()); self.assertFalse(copied.exists()); self.assertEqual(existing.read_bytes(),b'keep me')
    def test_move_and_undo(self):
        self.apply('move'); self.assertFalse(self.file.exists())
        self.undo(); self.assertEqual(sorter.digest(self.file),self.sha)
    def test_changed_source_refused(self):
        self.file.write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.apply('move')
        self.assertTrue(self.file.exists())
    def test_undo_changed_destination_refused(self):
        self.apply(); dst=self.output/'2'/'clip.mp4'; dst.write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.undo()
        self.assertEqual(dst.read_bytes(),b'changed')
    def test_undo_original_collision_refused(self):
        self.apply('move'); self.file.write_bytes(b'new original')
        with self.assertRaises(RuntimeError): self.undo()
        self.assertEqual(self.file.read_bytes(),b'new original')
    def test_crash_after_publish_resumes_without_duplicate(self):
        real=sorter.publish
        def crash(stage,dst): real(stage,dst); raise RuntimeError('simulated crash')
        with patch.object(sorter,'publish',crash):
            with self.assertRaises(RuntimeError): self.apply('move')
        self.assertTrue(self.file.exists())
        self.apply('move'); self.assertFalse(self.file.exists())
        self.assertEqual(len(list((self.output/'2').iterdir())),1)
        self.undo(); self.assertEqual(sorter.digest(self.file),self.sha)
    def test_unowned_identical_collision_preserved(self):
        def crash(*args): raise RuntimeError('before copy')
        with patch.object(sorter,'verified_copy',crash):
            with self.assertRaises(RuntimeError): self.apply()
        unowned=self.output/'2'/'clip.mp4'; unowned.write_bytes(self.file.read_bytes())
        self.apply(); self.undo()
        self.assertTrue(unowned.exists())
    def test_partial_copy_resumed(self):
        def partial(src,stage,sha): stage.write_bytes(b'partial'); raise RuntimeError('interrupted')
        with patch.object(sorter,'verified_copy',partial):
            with self.assertRaises(RuntimeError): self.apply()
        self.apply(); self.assertEqual(sorter.digest(self.output/'2'/'clip.mp4'),self.sha)
    def test_cancel_prepared_operation(self):
        with patch.object(sorter,'verified_copy',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.apply()
        self.undo(); self.assertTrue(self.file.exists())
        self.assertEqual(self.state.db.execute('SELECT status FROM operations').fetchone()[0],'undone')
    def test_incomplete_preview_refused(self):
        sorter.atomic_json(self.state.work/'plan.json',dict(output=str(self.output),complete=False))
        with self.assertRaises(RuntimeError): self.apply()
        self.assertFalse(self.output.exists())
    def test_selected_input_mismatch_refused_before_operations(self):
        sorter.atomic_json(self.state.work/'plan.json',dict(input=str(self.src),output=str(self.output),complete=True))
        args=argparse.Namespace(mode='move',expected_input=self.root/'other')
        with self.assertRaisesRegex(RuntimeError,'different input'):
            sorter.apply(args,self.state)
        self.assertTrue(self.file.exists()); self.assertFalse(self.output.exists())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM operations').fetchone()[0],0)
    def test_selected_output_mismatch_refused(self):
        sorter.atomic_json(self.state.work/'plan.json',dict(input=str(self.src),output=str(self.output),complete=True))
        with self.assertRaisesRegex(RuntimeError,'different output'):
            sorter.apply(argparse.Namespace(mode='copy',expected_output=self.root/'other'),self.state)
        self.assertFalse(self.output.exists())
    def test_changed_recursion_refused(self):
        with self.assertRaisesRegex(RuntimeError,'subfolders has changed'):
            sorter.apply(argparse.Namespace(mode='copy',expected_recursive='true'),self.state)
        self.assertFalse(self.output.exists())
    def test_missing_plan_explains_preview(self):
        (self.state.work/'plan.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'Preview / Resume first'):
            self.apply()
    def test_undo_copy_preserved_when_original_missing(self):
        self.apply(); self.file.unlink()
        with self.assertRaises(RuntimeError): self.undo()
        self.assertTrue((self.output/'2'/'clip.mp4').is_file())
    def test_crash_during_restore_resumes(self):
        self.apply('move'); real=sorter.publish
        def crash(stage,dst): real(stage,dst); raise RuntimeError('after restore')
        with patch.object(sorter,'publish',crash):
            with self.assertRaises(RuntimeError): self.undo()
        self.assertTrue(self.file.exists()); self.undo()
        self.assertEqual(sorter.digest(self.file),self.sha)
        self.assertFalse((self.output/'2'/'clip.mp4').exists())

if __name__=='__main__': unittest.main()
