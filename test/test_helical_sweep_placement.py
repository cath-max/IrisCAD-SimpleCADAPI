"""Geometry must not depend on whether operation recording is enabled."""
import math
import unittest
from contextlib import nullcontext
import simplecadapi as scad
from simplecadapi.graph import GraphSession
from simplecadapi.kernel.ocp_properties import bounding_box
from OCP.gp import gp_Ax3, gp_Pnt, gp_Dir
from OCP.BRepCheck import BRepCheck_Analyzer

class TestHelicalSweepPlacement(unittest.TestCase):
    def test_positioned_profile_matches_recorded_and_explicit_sweep(self):
        for center, direction in [((0,0,0),(0,0,1)), ((7,-13,4),(0,0,1)), ((7,13,19),(0,0,-1)), ((3,4,5),(1,0,0))]:
            with self.subTest(center=center, direction=direction):
                radius, pitch, height, wire_radius = 10, 3.8, 7.6, 1.5
                axes=gp_Ax3(gp_Pnt(*center),gp_Dir(*direction))
                x,y,z=axes.XDirection(),axes.YDirection(),axes.Direction()
                start=tuple(center[i]+radius*x.Coord(i+1) for i in range(3))
                normal=tuple(radius*y.Coord(i+1)+pitch/(2*math.pi)*z.Coord(i+1) for i in range(3))
                shapes=[]
                for recording in (False, True):
                    with GraphSession() if recording else nullcontext():
                        profile=scad.make_circle_rwire(start,wire_radius,normal=normal)
                        shapes.append(scad.helical_sweep_rsolid(profile,pitch,height,radius,center=center,dir=direction))
                profile=scad.make_circle_rwire(start,wire_radius,normal=normal)
                shapes.append(scad.sweep_rsolid(scad.make_face_from_wire_rface(profile),scad.make_helix_rwire(pitch,height,radius,center=center,dir=direction),is_frenet=True))
                expected_volume=math.pi*wire_radius**2 * math.hypot(2*math.pi*radius,pitch)*(height/pitch)
                reference=bounding_box(shapes[-1].wrapped)
                for shape in shapes:
                    self.assertTrue(BRepCheck_Analyzer(shape.wrapped).IsValid())
                    self.assertAlmostEqual(shape.get_volume(),expected_volume,delta=expected_volume*0.005)
                    bounds=bounding_box(shape.wrapped)
                    for key in ('xmin','ymin','zmin','xmax','ymax','zmax'):
                        self.assertAlmostEqual(getattr(bounds,key),getattr(reference,key),delta=1e-4)

if __name__=='__main__':
    unittest.main()
