#! ironpython
# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.UI.Selection import ObjectType
import math

doc = revit.doc
uidoc = revit.uidoc

# --- HELPER FUNCTIONS ---

def get_element_data(element):
    """
    Get start point and vector of the element.
    """
    loc = element.Location
    
    # 1. Curve-based (Beams, Slanted Columns)
    if isinstance(loc, DB.LocationCurve):
        curve = loc.Curve
        if isinstance(curve, DB.Line):
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            vector = p1 - p0
            return p0, vector
            
    # 2. Point-based (Vertical Columns)
    elif isinstance(loc, DB.LocationPoint):
        p0 = loc.Point
        return p0, DB.XYZ.BasisZ
        
    return None, None

def get_param_double(elem, names):
    """Helper to get a double parameter by multiple possible names."""
    for n in names:
        p = elem.LookupParameter(n)
        if p and p.HasValue:
            return p.AsDouble()
    return None

def create_section(element, point, vector, view_family_type, section_name):
    """Create a section view and return it."""
    
    # Check if vertical (Columns)
    norm_vec = vector.Normalize()
    is_vertical = norm_vec.IsAlmostEqualTo(DB.XYZ.BasisZ) or norm_vec.IsAlmostEqualTo(-DB.XYZ.BasisZ)
    
    t = DB.Transform.Identity
    t.Origin = point
    
    if is_vertical:
        # PLAN ORIENTATION (Standard Plan View: Looking Down)
        # BasisZ points Towards Viewer (Up). Camera Looks Down (-Z).
        t.BasisZ = DB.XYZ.BasisZ 
        t.BasisY = DB.XYZ.BasisY  # Up is Global Y (North)
        t.BasisX = DB.XYZ.BasisX  # Right is Global X (East)
        
    else:
        # BEAM ORIENTATION
        # BasisZ = ViewDir (Normal towards viewer). Camera looks -ViewDir.
        # If we want to look along vector P0->P1:
        # Look = Vector. BasisZ = -Vector.
        
        # Current logic: BasisZ = Vector. 
        # So we look P1->P0. This is acceptable for cross section.
        view_dir = norm_vec
        
        # Default Up (Global Z)
        up = DB.XYZ.BasisZ
        
        right = up.CrossProduct(view_dir)
        actual_up = view_dir.CrossProduct(right)
        
        t.BasisX = right
        t.BasisY = actual_up
        t.BasisZ = view_dir
    
    # 2. BoundingBox
    width = 3.0 
    height = 3.0 
    
    elem_type = doc.GetElement(element.GetTypeId())
    
    # Try to find dimensions to size box
    b_val = get_param_double(elem_type, ["b", "Width", "Beam Width"])
    h_val = get_param_double(elem_type, ["h", "Height", "Beam Height", "Depth"])
    d_val = get_param_double(elem_type, ["Diameter", "D"]) 
    
    if d_val:
        b_val = d_val
        h_val = d_val
        
    if b_val:
        width = b_val * 4.0 
    if h_val:
        height = h_val * 4.0 
        
    # Center the box
    min_pt = DB.XYZ(-width/2.0, -height/2.0, -1.0) 
    max_pt = DB.XYZ(width/2.0, height/2.0, 1.0)
    
    bbox = DB.BoundingBoxXYZ()
    bbox.Transform = t
    bbox.Min = min_pt
    bbox.Max = max_pt
    
    try:
        section = DB.ViewSection.CreateSection(doc, view_family_type.Id, bbox)
        try:
            section.Name = section_name
        except:
             section.Name = "{}_{}".format(section_name, element.Id)

        return section
    except Exception as e:
        print("Failed to create section for element {}: {}".format(element.Id, e))
        return None

def create_dimensions(view, element):
    """
    Create dimensions for the element in the given view.
    Places Width Dimensions at TOP.
    Places Height Dimensions at LEFT.
    """
    try:
        opt = DB.Options()
        opt.ComputeReferences = True
        opt.View = view 
        opt.IncludeNonVisibleObjects = False
        
        geom_elem = element.get_Geometry(opt)
        if not geom_elem: return
        
        solids = []
        for obj in geom_elem:
            if isinstance(obj, DB.Solid) and obj.Volume > 0:
                solids.append(obj)
            elif isinstance(obj, DB.GeometryInstance):
                inst_geom = obj.GetInstanceGeometry()
                for inst_obj in inst_geom:
                    if isinstance(inst_obj, DB.Solid) and inst_obj.Volume > 0:
                        solids.append(inst_obj)
                        
        if not solids: return
        
        view_right = view.RightDirection
        view_up = view.UpDirection
        view_origin = view.Origin
        
        faces_vertical = [] # Faces Normal || Right (Sides) -> For Width Dim
        faces_horizontal = [] # Faces Normal || Up (Top/Bottom) -> For Height Dim
        
        # Bounds in View Space (U, V)
        min_u = 100000.0
        max_u = -100000.0
        min_v = 100000.0
        max_v = -100000.0
        
        sol = solids[0] 

        for face in sol.Faces:
            if not isinstance(face, DB.PlanarFace): continue
            
            normal = face.FaceNormal
            origin = face.Origin
            
            # Project origin to view plane coords
            v_orig = origin - view_origin
            u = v_orig.DotProduct(view_right)
            v = v_orig.DotProduct(view_up)
            
            # Check alignment (Allow for opposite direction)
            # Vertical Face -> For Width
            if abs(normal.DotProduct(view_right)) > 0.9:
                faces_vertical.append(face)
                min_u = min(min_u, u)
                max_u = max(max_u, u)
                
            # Horizontal Face -> For Height
            elif abs(normal.DotProduct(view_up)) > 0.9:
                faces_horizontal.append(face)
                min_v = min(min_v, v)
                max_v = max(max_v, v)

        # 50mm Offset in Feet
        offset = 50.0 / 304.8 
        
        # --- WIDTH DIMENSION (Top) ---
        if len(faces_vertical) >= 2:
            # Sort Left to Right
            faces_vertical.sort(key=lambda f: (f.Origin - view_origin).DotProduct(view_right))
            
            ref_array_w = DB.ReferenceArray()
            # Pick Extremes
            ref_array_w.Append(faces_vertical[0].Reference)
            ref_array_w.Append(faces_vertical[-1].Reference)
            
            # Position at TOP (Max V + Offset)
            line_v = max_v + offset
            
            p_start = view_origin + view_right*(min_u) + view_up*(line_v)
            p_end = view_origin + view_right*(max_u) + view_up*(line_v)
            
            line_w = DB.Line.CreateBound(p_start, p_end)
            doc.Create.NewDimension(view, line_w, ref_array_w)
            
        # --- HEIGHT DIMENSION (Left) ---
        if len(faces_horizontal) >= 2:
            # Sort Bottom to Top
            faces_horizontal.sort(key=lambda f: (f.Origin - view_origin).DotProduct(view_up))
            
            ref_array_h = DB.ReferenceArray()
            # Pick Extremes
            ref_array_h.Append(faces_horizontal[0].Reference)
            ref_array_h.Append(faces_horizontal[-1].Reference)
            
            # Position at LEFT (Min U - Offset)
            line_u = min_u - offset
            
            p_start = view_origin + view_right*(line_u) + view_up*(min_v)
            p_end = view_origin + view_right*(line_u) + view_up*(max_v)
            
            line_h = DB.Line.CreateBound(p_start, p_end)
            doc.Create.NewDimension(view, line_h, ref_array_h)
             
    except Exception as e:
        print("Dim Warning: " + str(e))

def get_section_view_type():
    view_types = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements()
    for vt in view_types:
        if vt.ViewFamily == DB.ViewFamily.Section:
            return vt
    return None

# --- UI CLASS ---

class CreateSectionsWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, script.get_bundle_file('ui.xaml'))
        self.section_type = get_section_view_type()
        
        if not self.section_type:
            forms.alert("No 'Section' View Type found.")
            self.Close()

    def select_beams_click(self, sender, args):
        self.Hide()
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select Beams")
        except: self.Show(); return
        if not refs: self.Show(); return
        
        do_dims = self.chkDimsBeam.IsChecked

        t = DB.Transaction(doc, "Create Beam Sections")
        t.Start()
        
        count = 0
        beams_processed = 0
        
        for ref in refs:
            beam = doc.GetElement(ref)
            if beam.Category.Id.IntegerValue != int(DB.BuiltInCategory.OST_StructuralFraming):
                continue

            p0, vector = get_element_data(beam)
            if not vector: continue
            
            if vector.Normalize().IsAlmostEqualTo(DB.XYZ.BasisZ): continue

            mark_val = beam.LookupParameter("Mark").AsString() or str(beam.Id)

            p_1_6 = p0 + vector * (1.0/6.0)
            p_1_2 = p0 + vector * 0.5

            s1 = create_section(beam, p_1_6, vector, self.section_type, "{} - SUPPORT".format(mark_val))
            s2 = create_section(beam, p_1_2, vector, self.section_type, "{} - MID".format(mark_val))

            if s1 or s2:
                beams_processed += 1
                if s1: 
                    count += 1
                    if do_dims: create_dimensions(s1, beam)
                if s2: 
                    count += 1
                    if do_dims: create_dimensions(s2, beam)
        
        t.Commit()
        forms.alert("Created {} sections for {} beams.".format(count, beams_processed))
        self.Show()

    def select_columns_click(self, sender, args):
        self.Hide()
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select Columns")
        except: self.Show(); return
        if not refs: self.Show(); return

        do_dims = self.chkDimsCol.IsChecked

        t = DB.Transaction(doc, "Create Column Sections")
        t.Start()
        
        count = 0
        cols_processed = 0
        
        for ref in refs:
            col = doc.GetElement(ref)
            if col.Category.Id.IntegerValue not in [int(DB.BuiltInCategory.OST_Columns), int(DB.BuiltInCategory.OST_StructuralColumns)]:
                continue

            p0, vector = get_element_data(col)
            if not vector: continue

            bbox = col.get_BoundingBox(None)
            if bbox:
                p_mid = (bbox.Min + bbox.Max) * 0.5
            else:
                p_mid = p0 + vector * 1.5 
            
            mark_val = col.LookupParameter("Mark").AsString() or str(col.Id)
            
            s = create_section(col, p_mid, vector, self.section_type, "{} - SECTION".format(mark_val))

            if s:
                count += 1
                cols_processed += 1
                if do_dims: create_dimensions(s, col)
        
        t.Commit()
        
        if count == 0 and cols_processed == 0:
             forms.alert("Created 0 sections.")
        else:
             forms.alert("Created {} sections for {} columns.".format(count, cols_processed))
             
        self.Show()

if __name__ == '__main__':
    CreateSectionsWindow().ShowDialog()
