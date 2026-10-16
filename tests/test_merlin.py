import sys
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import merlin_placefiles as m

class MerlinTests(unittest.TestCase):
    now=datetime(2026,10,16,8,22,tzinfo=timezone.utc)
    def row(self,**kw):
        d=dict(id=1,event_date='2026-10-16',event_time='08:21:00.0000000',event_datetime='2026-10-16T08:21:00',lat_decimal=28.5,lon_decimal=-80.6,signal_strength=12)
        d.update(kw)
        return d
    def event(self,**kw):
        return m.parse_api([self.row(**kw)])[0][0]
    def test_cc_all_density_colors_and_symbols(self):
        events=[]
        for i,n in enumerate([1,5,20,50,100,250]):
            for j in range(n): events.append(self.event(id=i*1000+j+1,lon_decimal=-80.6+i*.02))
        text=m.cc_placefile(events,self.now,15,0)
        first=text.split('TimeRange: ')[1]
        self.assertEqual(first.count('Object:'),6)
        self.assertEqual(first.count('Text: 0, 0, 2, "l"'),6)
        for c in m.COLORS:self.assertIn('Color: '+c,first)
        self.assertNotIn('Polygon:',text)
        self.assertNotIn('CC density 08:',text)
        self.assertIn('Font: 2, 10, 0, "Wingdings"',text)
    def test_time_boundaries_and_decay(self):
        e=self.event()
        text=m.cc_placefile([e],self.now,1,0)
        self.assertEqual(text.count('Object:'),1)
        at_frame=self.event(event_time='08:22:00',event_datetime='2026-10-16T08:22:00')
        self.assertNotIn('Object:',m.cc_placefile([at_frame],self.now,1,0))
        self.assertNotIn('Object:',m.cc_placefile([e],self.now+timedelta(minutes=15),15,0))
    def test_cg_precision_hover_units(self):
        e=self.event(event_time='08:21:00.0000001')
        text=m.cg_placefile([e],self.now,15,60)
        self.assertIn('TimeRange: 2026-10-16T08:21:01 2026-10-16T08:36:00',text)
        self.assertIn('Color: 255 210 80',text)
        self.assertIn('1, "+"',text)
        self.assertIn('08:21:00.0000001Z',text)
        self.assertIn('(source units)',text)
        self.assertNotIn('kA',text)
    def test_overlap_dedup_and_empty(self):
        e=self.row()
        with patch.object(m,'get_json',return_value=[e]):
            events,rejected=m.fetch_window('c2g',self.now-timedelta(minutes=10),self.now)
        self.assertEqual(len(events),1)
        self.assertEqual(m.parse_api([]),([],0))
        with self.assertRaises(ValueError):m.parse_api({'error':'failed'})
        a,b=m.parse_api([self.row(id=1,event_time='08:21:00.0000001'),self.row(id=2,event_time='08:21:00.0000002')])
        self.assertEqual(len(a),2)

if __name__=='__main__':unittest.main()
