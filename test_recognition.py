"""Synthetic parser checks; real clip accuracy is checked separately."""
import unittest
import numpy as np
from prototype import Reader

def row(text,x,y,confidence=.9):
    return dict(text=text,x=x,y=y,confidence=confidence)

class ReportParsing(unittest.TestCase):
    def reader(self,rows):
        reader=Reader.__new__(Reader)
        reader.read=lambda frame:rows
        return reader
    def test_damage_and_killed_you_are_zero(self):
        rows=[row('COMBAT REPORT',.5,.1),row('22',.14,.18),row('73',.14,.265),
              row('KILLED YOU',.86,.21),row('[N] SHOW/HIDE REPORT',.5,.8)]
        result=self.reader(rows).report(np.zeros((1080,1920,3),dtype=np.uint8))
        self.assertEqual(result['kills'],0); self.assertTrue(result['zero_verified'])
    def test_dropped_kill_label_cannot_become_zero(self):
        frame=np.zeros((1080,1920,3),dtype=np.uint8)
        # Synthetic outgoing red stripe at the panel's normalized location.
        frame[302:361,1509:1516]=(45,45,220)
        rows=[row('COMBAT REPORT',.5,.1),row('160',.14,.18),row('[N] SHOW/HIDE REPORT',.5,.8)]
        result=self.reader(rows).report(frame)
        self.assertFalse(result['zero_verified']); self.assertFalse(result['labels_complete'])
    def test_exact_left_killed_only(self):
        rows=[row('COMBAT REPORT',.5,.1),row('KILLED',.14,.2),row('ASSIST',.14,.285),
              row('KILLED YOU',.86,.2),row('KILLED BY SOVA',.5,.05),row('[N] SHOW/HIDE REPORT',.5,.8)]
        result=self.reader(rows).report(np.zeros((1080,1920,3),dtype=np.uint8))
        self.assertEqual(result['kills'],1);self.assertEqual(result['assists'],1)
        self.assertFalse(result['labels_complete'])
    def test_no_header_is_not_zero(self):
        self.assertIsNone(self.reader([row('KILLED',.14,.2)]).report(np.zeros((1080,1920,3),dtype=np.uint8)))

if __name__=='__main__': unittest.main()
