# -*- coding: utf-8 -*-
__title__ = 'Beam Rebar'
__doc__ = 'Parametric rebar editor with auto-spacing for multi-layer support.'

from pyrevit import revit, DB, forms, script
import os
import clr
import math
import json
import traceback

clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
from System.Windows import Window, Point, UIElement
from System.Windows.Controls import Canvas, ToolTip, ComboBox
import System.Windows.Shapes as Shapes
from System.Windows.Shapes import Rectangle, Ellipse
from System.Windows.Media import Brushes, Color, SolidColorBrush
from System.Collections.Generic import List

# --- Constants ---
FRAMING_CAT_ID = int(DB.BuiltInCategory.OST_StructuralFraming)
COLUMN_CAT_ID = int(DB.BuiltInCategory.OST_StructuralColumns)
FOOTING_CAT_ID = int(DB.BuiltInCategory.OST_StructuralFoundation)

# --- Selection Filter ---
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
class BeamSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        try:
            if elem.Category:
                cid = elem.Category.Id.IntegerValue
                if cid == FRAMING_CAT_ID or cid == COLUMN_CAT_ID or cid == FOOTING_CAT_ID:
                    return True
        except: pass
        return False
    def AllowReference(self, ref, pt): return True

class FootingSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        try:
            if elem.Category and elem.Category.Id.IntegerValue == FOOTING_CAT_ID:
                return True
        except: pass
        return False
    def AllowReference(self, ref, pt): return True

# --- Helper Classes ---
# --- SECTION TOOL HELPERS ---
def get_element_data_sec(element):
    loc = element.Location
    if isinstance(loc, DB.LocationCurve):
        curve = loc.Curve
        if isinstance(curve, DB.Line):
            return curve.GetEndPoint(0), curve.GetEndPoint(1) - curve.GetEndPoint(0)
    elif isinstance(loc, DB.LocationPoint):
        return loc.Point, DB.XYZ.BasisZ
    return None, None

def create_section_view(doc, element, point, vector, view_family_type, name):
    norm_vec = vector.Normalize()
    is_vertical = norm_vec.IsAlmostEqualTo(DB.XYZ.BasisZ) or norm_vec.IsAlmostEqualTo(-DB.XYZ.BasisZ)
    t = DB.Transform.Identity
    t.Origin = point
    
    if is_vertical:
        t.BasisZ = DB.XYZ.BasisZ
        t.BasisY = DB.XYZ.BasisY
        t.BasisX = DB.XYZ.BasisX
    else:
        view_dir = norm_vec
        up = DB.XYZ.BasisZ
        right = up.CrossProduct(view_dir)
        t.BasisX = right
        t.BasisY = view_dir.CrossProduct(right)
        t.BasisZ = view_dir

    w, h = 3.0, 3.0
    # Try params
    el_type = doc.GetElement(element.GetTypeId())
    def _p(e, n_list):
        for n in n_list:
            p = e.LookupParameter(n)
            if p and p.HasValue: return p.AsDouble()
        return None
    
    bv = _p(el_type, ["b", "Width", "Beam Width", "Diameter", "D"])
    hv = _p(el_type, ["h", "Height", "Beam Height", "Depth", "Diameter", "D"])
    
    if bv: w = bv * 4.0
    if hv: h = hv * 4.0
    
    bbox = DB.BoundingBoxXYZ()
    bbox.Transform = t
    bbox.Min = DB.XYZ(-w/2, -h/2, -1.0)
    bbox.Max = DB.XYZ(w/2, h/2, 1.0)
    
    try:
        vs = DB.ViewSection.CreateSection(doc, view_family_type.Id, bbox)
        try: vs.Name = name
        except: vs.Name = "{}_{}".format(name, element.Id)
        return vs
    except Exception as ex: 
        print("CreateSection Error: " + str(ex))
        return None

def create_section_dims(doc, view, element):
    try:
        opt = DB.Options()
        opt.ComputeReferences = True
        opt.View = view
        opt.IncludeNonVisibleObjects = False
        geom = element.get_Geometry(opt)
        
        solid = None
        if geom:
            for g in geom:
                if isinstance(g, DB.Solid) and g.Volume > 0: solid = g; break
                elif isinstance(g, DB.GeometryInstance):
                    for gi in g.GetInstanceGeometry():
                        if isinstance(gi, DB.Solid) and gi.Volume > 0: solid = gi; break
        
        if not solid: return

        v_right = view.RightDirection
        v_up = view.UpDirection
        v_org = view.Origin
        
        f_vert = []
        f_horz = []
        
        min_u, max_u = 1e9, -1e9
        min_v, max_v = 1e9, -1e9

        for f in solid.Faces:
            if isinstance(f, DB.PlanarFace):
                n = f.FaceNormal
                # Check alignment
                if abs(n.DotProduct(v_right)) > 0.9: 
                    f_vert.append(f)
                    u = (f.Origin - v_org).DotProduct(v_right)
                    min_u = min(min_u, u); max_u = max(max_u, u)
                elif abs(n.DotProduct(v_up)) > 0.9: 
                    f_horz.append(f)
                    v = (f.Origin - v_org).DotProduct(v_up)
                    min_v = min(min_v, v); max_v = max(max_v, v)
        
        off = 50.0/304.8
        
        # Width Dim (Top)
        if len(f_vert) >= 2:
            f_vert.sort(key=lambda f: (f.Origin - v_org).DotProduct(v_right))
            ref_a = DB.ReferenceArray()
            ref_a.Append(f_vert[0].Reference)
            ref_a.Append(f_vert[-1].Reference)
            l_v = max_v + off
            p1 = v_org + v_right*min_u + v_up*l_v
            p2 = v_org + v_right*max_u + v_up*l_v
            doc.Create.NewDimension(view, DB.Line.CreateBound(p1, p2), ref_a)

        # Height Dim (Left)
        if len(f_horz) >= 2:
            f_horz.sort(key=lambda f: (f.Origin - v_org).DotProduct(v_up))
            ref_a = DB.ReferenceArray()
            ref_a.Append(f_horz[0].Reference)
            ref_a.Append(f_horz[-1].Reference)
            l_u = min_u - off
            p1 = v_org + v_right*l_u + v_up*min_v
            p2 = v_org + v_right*l_u + v_up*max_v
            doc.Create.NewDimension(view, DB.Line.CreateBound(p1, p2), ref_a)

    except Exception as e: print("Dim Err: " + str(e))

class RebarPoint:
    def __init__(self, lx, ly, diameter_ft, bar_type_name):
        self.lx, self.ly = lx, ly 
        self.diameter_ft = diameter_ft
        self.type_name = bar_type_name

class ProfileManager:
    def __init__(self, doc=None):
        self.doc = doc
        self.file_path = os.path.join(os.path.dirname(__file__), "profiles.json")
        self.profiles = {}
        self.load_profiles()

    def load_profiles(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    self.profiles = json.load(f)
            except: self.profiles = {}
        
        if "Default" not in self.profiles:
            self.profiles["Default"] = {
                "End Sections": {"T1": 2, "T2": 0, "B1": 2, "B2": 0},
                "Middle Section": {"T1": 2, "T2": 0, "B1": 2, "B2": 0},
                "Global": {
                    "SideCover": 25, "EndOffset": 40, "EndSpacing": 150, "MidSpacing": 250,
                    "BeamWidth": 300, "BeamHeight": 600
                }
            }

    def save_profile(self, name, data):
        self.profiles[name] = data
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.profiles, f, indent=2)
            return True
        except: return False

    def delete_profile(self, name):
        if name in self.profiles and name != "Default":
            del self.profiles[name]
            try:
                with open(self.file_path, 'w') as f:
                    json.dump(self.profiles, f, indent=2)
                return True
            except: return False
        return False

class ParametricRebarWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        super(ParametricRebarWindow, self).__init__(xaml_file)
        self.beam_w_ft = 1.0 
        self.beam_h_ft = 2.0
        self.bar_types_data = [] 
        self.stirrup_types_data = []
        self.pm = None
        self.zone_configs = {
            "End Sections": {"T1": 2, "T2": 0, "B1": 2, "B2": 0},
            "Middle Section": {"T1": 2, "T2": 0, "B1": 2, "B2": 0}
        }
        self.current_zone = "End Sections"
        self.bars = {"End Sections": [], "Middle Section": []}

    def setup_data(self, bar_types_data, stirrup_types_data, profile_manager):
        self.bar_types_data = bar_types_data
        self.stirrup_types_data = stirrup_types_data
        self.pm = profile_manager
        
        self.populate_all_combos()
        
        # Events
        self.top_bar_type_selector.SelectionChanged += self.global_input_changed
        self.bot_bar_type_selector.SelectionChanged += self.global_input_changed
        self.stirrup_selector.SelectionChanged += self.global_input_changed
        self.side_cover.TextChanged += self.global_input_changed
        self.end_spacing.TextChanged += self.global_input_changed
        self.mid_spacing.TextChanged += self.global_input_changed
        self.beam_width_ui.TextChanged += self.global_input_changed
        self.beam_height_ui.TextChanged += self.global_input_changed
        self.beam_side_type.SelectionChanged += self.global_input_changed
        self.beam_side_qty.SelectionChanged += self.global_input_changed
        self.spacer_type.SelectionChanged += self.global_input_changed
        self.spacer_spacing.TextChanged += self.global_input_changed
        
        self.top_L2_type.SelectionChanged += self.global_input_changed
        self.bot_L2_type.SelectionChanged += self.global_input_changed
        self.chk_top_same.Click += self.toggle_bar_types
        self.chk_bot_same.Click += self.toggle_bar_types
        
        # Zone-specific Beam Events
        for cb in [self.top_L1_qty, self.top_L2_qty, self.bot_L1_qty, self.bot_L2_qty]:
            cb.SelectionChanged += self.zone_input_changed

        self.profile_selector.SelectionChanged += self.profile_changed
        self.save_profile_btn.Click += self.save_profile_click
        self.delete_profile_btn.Click += self.delete_profile_click

        # Footing Events
        self.footing_profile_selector.SelectionChanged += self.footing_profile_changed
        self.save_footing_profile_btn.Click += self.save_footing_profile_click
        self.del_footing_profile_btn.Click += self.delete_footing_profile_click

        # Column Events
        for el in [self.col_width_ui, self.col_depth_ui, self.col_cover]:
            el.TextChanged += self.col_input_changed
        for el in [self.col_corner_type, self.col_side_x_type, self.col_side_x_qty, 
                   self.col_side_y_type, self.col_side_y_qty, self.col_tie_type]:
            el.SelectionChanged += self.col_input_changed
        self.col_profile_selector.SelectionChanged += self.col_profile_changed
        self.save_col_profile_btn.Click += self.save_col_profile_click
        self.del_col_profile_btn.Click += self.delete_col_profile_click

        self.update_zoning_info()
        self.load_initial_profile()
        self.calculate_all_zones()
        self.toggle_bar_types(None, None) # Ensure UI correct
        self.draw_col_preview() 

    def populate_all_combos(self):
        # 1. Main Beam Combos
        for cb in [self.top_L1_qty, self.top_L2_qty, self.bot_L1_qty, self.bot_L2_qty]:
            cb.Items.Clear()
            for i in range(11): cb.Items.Add(str(i))
            cb.SelectedIndex = 0
            
        self.beam_side_qty.Items.Clear()
        for i in range(0, 11, 2): self.beam_side_qty.Items.Add(str(i))
        self.beam_side_qty.SelectedIndex = 0
        
        for cb in [self.top_bar_type_selector, self.top_L2_type, self.bot_bar_type_selector, self.bot_L2_type, self.beam_side_type]:
            cb.Items.Clear()
            for data in self.bar_types_data: cb.Items.Add(data[0])
            cb.SelectedIndex = 0
        
        self.stirrup_selector.Items.Clear()
        for data in self.stirrup_types_data: self.stirrup_selector.Items.Add(data[0])
        self.stirrup_selector.SelectedIndex = 0

        self.spacer_type.Items.Clear()
        self.spacer_type.Items.Add("None")
        for d in self.bar_types_data: self.spacer_type.Items.Add(d[0])
        self.spacer_type.SelectedIndex = 0

        # 2. Column Combos
        for cb in [self.col_corner_type, self.col_side_x_type, self.col_side_y_type]:
            cb.Items.Clear()
            for d in self.bar_types_data: cb.Items.Add(d[0])
            cb.SelectedIndex = 0
            
        self.col_tie_type.Items.Clear()
        for data in self.stirrup_types_data: self.col_tie_type.Items.Add(data[0])
        self.col_tie_type.SelectedIndex = 0
        
        for cb in [self.col_side_x_qty, self.col_side_y_qty]:
            cb.Items.Clear()
            for i in range(11): cb.Items.Add(str(i))
            cb.SelectedIndex = 0

        # 3. Footing Combos
        for cb in [self.footing_bx_type, self.footing_by_type, self.footing_tx_type, self.footing_ty_type]:
            cb.Items.Clear()
            idx_12 = 0
            for i, d in enumerate(self.bar_types_data): 
                cb.Items.Add(d[0])
                if "12" in d[0]: idx_12 = i
            cb.SelectedIndex = idx_12

        # 4. Profile Selectors
        self.profile_selector.Items.Clear()
        self.col_profile_selector.Items.Clear()
        self.footing_profile_selector.Items.Clear()
        
        self.profile_selector.Items.Add("Default")
        self.col_profile_selector.Items.Add("Default")
        self.footing_profile_selector.Items.Add("Default")
        
        for name, data in sorted(self.pm.profiles.items()):
            p_type = data.get("Type")
            if p_type == "Column":
                self.col_profile_selector.Items.Add(name)
            elif p_type == "Footing":
                self.footing_profile_selector.Items.Add(name)
            else: # Beam / Default
                if name != "Default": self.profile_selector.Items.Add(name)
        
        self.profile_selector.SelectedIndex = 0
        self.col_profile_selector.SelectedIndex = 0
        self.footing_profile_selector.SelectedIndex = 0

        self.profile_selector.SelectedIndex = 0
        self.col_profile_selector.SelectedIndex = 0
        self.footing_profile_selector.SelectedIndex = 0

    def col_input_changed(self, sender, e):
        self.draw_col_preview()

    # --- SECTION TOOL METHODS ---
    def get_sec_type(self):
        vts = DB.FilteredElementCollector(revit.doc).OfClass(DB.ViewFamilyType).ToElements()
        for vt in vts:
            if vt.ViewFamily == DB.ViewFamily.Section: return vt
        return None

    def sec_beam_click(self, sender, args):
        self.Hide()
        try:
            filt = BeamSelectionFilter()
            refs = revit.uidoc.Selection.PickObjects(ObjectType.Element, filt, "Select Beams")
        except: self.Show(); return
        if not refs: self.Show(); return
        
        vt = self.get_sec_type()
        if not vt: forms.alert("No Section View Type"); self.Show(); return
        
        use_custom = self.chk_beam_custom.IsChecked
        custom_locs = []
        if use_custom:
            try:
                parts = self.txt_beam_locs.Text.split(',')
                for p in parts: custom_locs.append(float(p.strip()))
            except: forms.alert("Invalid Custom Locations format. Use comma separated numbers (e.g. 0.25, 0.5)"); self.Show(); return

        with revit.Transaction("Create Beam Sections"):
            cnt = 0
            for r in refs:
                el = revit.doc.GetElement(r)
                if el.Category.Id.IntegerValue != FRAMING_CAT_ID: continue
                p0, vec = get_element_data_sec(el)
                if not p0 or not vec: 
                    log("Skipping Non-Linear or Invalid Element: " + str(el.Id))
                    continue
                
                length = vec.GetLength()
                if length < 0.001: 
                    log("Skipping zero-length element: " + str(el.Id))
                    continue
                if vec.Normalize().IsAlmostEqualTo(DB.XYZ.BasisZ): 
                    log("Skipping vertical element in beam tool: " + str(el.Id))
                    continue
                
                mark = el.LookupParameter("Mark").AsString() or str(el.Id)
                
                locs_to_create = [] # (ratio, suffix)
                if use_custom:
                    for l in custom_locs:
                         # Ensure 0-1 range or assume distance if > 1?
                         # Let's assume Ratio 0-1.
                         ratio = l
                         if ratio > 1.0: ratio = ratio / (length*304.8) # auto-detect mm input? rarely used. stick to ratio.
                         
                         suffix = " - L={:.0f}".format(length * 304.8 * ratio)
                         locs_to_create.append((ratio, suffix))
                else:
                    locs_to_create.append((1.0/6.0, " - SUPPORT"))
                    locs_to_create.append((0.5, " - MID"))

                for ratio, suffix in locs_to_create:
                    s = create_section_view(revit.doc, el, p0 + vec*ratio, vec, vt, mark + suffix)
                    if s: 
                        cnt+=1
                        if self.chk_dims_beam.IsChecked: create_section_dims(revit.doc, s, el)
                        
            if cnt == 0:
                forms.alert("No beam sections created. Ensure you selected straight horizontal beams.")
            else:
                forms.alert("Created {} beam sections.".format(cnt))
        self.Show()

    def sec_col_click(self, sender, args):
        self.Hide()
        try:
            filt = BeamSelectionFilter() # Filter handles columns too
            refs = revit.uidoc.Selection.PickObjects(ObjectType.Element, filt, "Select Columns")
        except: self.Show(); return
        if not refs: self.Show(); return

        vt = self.get_sec_type()
        if not vt: forms.alert("No Section View Type"); self.Show(); return

        use_custom = self.chk_col_custom.IsChecked
        custom_locs = []
        if use_custom:
            try:
                parts = self.txt_col_locs.Text.split(',')
                for p in parts: custom_locs.append(float(p.strip()))
            except: forms.alert("Invalid Custom Locations format."); self.Show(); return

        with revit.Transaction("Create Column Sections"):
             cnt = 0
             for r in refs:
                 el = revit.doc.GetElement(r)
                 cat = el.Category.Id.IntegerValue
                 if cat != COLUMN_CAT_ID: continue
                 p0, vec = get_element_data_sec(el)
                 if not p0 or not vec: 
                     log("Skipping invalid column: " + str(el.Id))
                     continue
                 bb = el.get_BoundingBox(None)
                 if not bb: continue
                 h_vec = bb.Max.Z - bb.Min.Z # Simple Z height
                 # Vec from get_element_data_sec for column is BasisZ?
                 # Actually get_element_data_sec returns (Point, BasisZ) for LocationPoint.
                 # Let's use BoundingBox Z range for ratios.
                 
                 z_min = bb.Min.Z
                 z_len = bb.Max.Z - bb.Min.Z
                 
                 mark = el.LookupParameter("Mark").AsString() or str(el.Id)
                 
                 locs_to_create = []
                 if use_custom:
                     for l in custom_locs:
                         ratio = l
                         suffix = " - H={:.0f}".format(z_len * 304.8 * ratio)
                         locs_to_create.append((ratio, suffix))
                 else:
                     locs_to_create.append((0.5, " - SECTION"))
                 
                 for ratio, suffix in locs_to_create:
                     # For column, origin + Z_offset
                     # p0 from get_element_data_sec is valid?
                     # Better to use Center of BB at specific Z
                     center_x = (bb.Min.X + bb.Max.X)/2.0
                     center_y = (bb.Min.Y + bb.Max.Y)/2.0
                     z_loc = z_min + z_len * ratio
                     
                     pt = DB.XYZ(center_x, center_y, z_loc)
                     # Vector? Column usually vertical -> BasisZ. Section needs to cut Horizontal -> ViewDir = BasisZ?
                     # No, Section Cut is Perpendicular to ViewDir.
                     # If we want a PLAN SECTION (Horizontal Cut), ViewDir should be Down/Up (BasisZ).
                     # "Detail View" or "Floor Plan".
                     # existing create_section_view handles logic based on 'vec'.
                     # For column, 'vec' is BasisZ.
                     # logic: if is_vertical (BasisZ): t.BasisZ=BasisZ.
                     # This creates a Floor Plan-like section?
                     # Actual Structural Column Section is a plan view.
                     # Let's trust existing logic works for "Cross Section".
                     
                     s = create_section_view(revit.doc, el, pt, vec, vt, mark + suffix)
                     if s:
                         cnt += 1
                         if self.chk_dims_col.IsChecked: create_section_dims(revit.doc, s, el)
             
             if cnt == 0:
                 forms.alert("No sections created. Please ensure you selected valid columns.")
             else:
                 forms.alert("Created {} sections.".format(cnt))
        self.Show()
        
    def col_profile_changed(self, sender, e):
        sel_name = self.col_profile_selector.SelectedItem
        if not sel_name or sel_name == "Default": return
        
        data = self.pm.profiles.get(sel_name)
        if not data: return
        
        try:
            self.col_width_ui.Text = str(data.get("ColWidth", 400))
            self.col_depth_ui.Text = str(data.get("ColDepth", 400))
            self.col_cover.Text = str(data.get("ColCover", 25))
            self.col_tie_spacing_end.Text = str(data.get("TieSpacingEnd", 100))
            self.col_tie_spacing_mid.Text = str(data.get("TieSpacingMid", 200))
            self.col_conf_height.Text = str(data.get("ConfHeight", 600))
            self.col_top_extension.Text = str(data.get("TopExtension", 0))
            
            def set_sel(cb, val):
                if val: cb.SelectedItem = val
                
            set_sel(self.col_corner_type, data.get("CornerType"))
            set_sel(self.col_side_x_type, data.get("SideXType"))
            set_sel(self.col_side_y_type, data.get("SideYType"))
            set_sel(self.col_tie_type, data.get("TieType"))
            
            self.col_side_x_qty.SelectedItem = str(data.get("SideXQty", 0))
            self.col_side_y_qty.SelectedItem = str(data.get("SideYQty", 0))
        except: pass
        
    def save_col_profile_click(self, sender, e):
        try:
            # Prompt for name
            from pyrevit.forms import ask_for_string
            p_name = ask_for_string(default="Col-Type-A", prompt="Enter Profile Name:", title="Save Column Profile")
            if not p_name: return
            
            data = {
                "Type": "Column",
                "ColWidth": self.col_width_ui.Text,
                "ColDepth": self.col_depth_ui.Text,
                "ColCover": self.col_cover.Text,
                "TieSpacingEnd": self.col_tie_spacing_end.Text,
                "TieSpacingMid": self.col_tie_spacing_mid.Text,
                "ConfHeight": self.col_conf_height.Text,
                "TopExtension": self.col_top_extension.Text,
                "CornerType": self.col_corner_type.SelectedItem,
                "SideXType": self.col_side_x_type.SelectedItem,
                "SideYType": self.col_side_y_type.SelectedItem,
                "TieType": self.col_tie_type.SelectedItem,
                "SideXQty": int(str(self.col_side_x_qty.SelectedItem)),
                "SideYQty": int(str(self.col_side_y_qty.SelectedItem))
            }
            
            self.pm.save_profile(p_name, data)
            self.populate_all_combos()
            self.col_profile_selector.SelectedItem = p_name
            forms.alert("Profile Saved!")
        except Exception as ex: forms.alert("Error saving: " + str(ex))

    def delete_col_profile_click(self, sender, e):
        sel_name = self.col_profile_selector.SelectedItem
        if not sel_name or sel_name == "Default": return
        
        if forms.alert("Delete profile '{}'?".format(sel_name), yes=True, no=True):
            self.pm.delete_profile(sel_name)
            self.populate_all_combos()
            forms.alert("Profile Deleted.")

    def footing_profile_changed(self, sender, e):
        sel_name = self.footing_profile_selector.SelectedItem
        if not sel_name or sel_name == "Default": return
        
        data = self.pm.profiles.get(sel_name)
        if not data: return
        
        try:
            self.footing_cover.Text = str(data.get("Cover", 50))
            self.chk_footing_top_mat.IsChecked = data.get("TopMat", False)
            
            self.footing_bx_spacing.Text = str(data.get("BXSpacing", 200))
            self.footing_by_spacing.Text = str(data.get("BYSpacing", 200))
            self.footing_tx_spacing.Text = str(data.get("TXSpacing", 200))
            self.footing_ty_spacing.Text = str(data.get("TYSpacing", 200))
            
            def set_sel(cb, val):
                if val: cb.SelectedItem = val
                
            set_sel(self.footing_bx_type, data.get("BXType"))
            set_sel(self.footing_by_type, data.get("BYType"))
            set_sel(self.footing_tx_type, data.get("TXType"))
            set_sel(self.footing_ty_type, data.get("TYType"))
        except: pass

    def save_footing_profile_click(self, sender, e):
        try:
            from pyrevit.forms import ask_for_string
            p_name = ask_for_string(default="F-Type-1", prompt="Enter Footing Profile Name:", title="Save Footing Profile")
            if not p_name: return
            
            data = {
                "Type": "Footing",
                "Cover": self.footing_cover.Text,
                "TopMat": self.chk_footing_top_mat.IsChecked,
                "BXType": self.footing_bx_type.SelectedItem,
                "BXSpacing": self.footing_bx_spacing.Text,
                "BYType": self.footing_by_type.SelectedItem,
                "BYSpacing": self.footing_by_spacing.Text,
                "TXType": self.footing_tx_type.SelectedItem,
                "TXSpacing": self.footing_tx_spacing.Text,
                "TYType": self.footing_ty_type.SelectedItem,
                "TYSpacing": self.footing_ty_spacing.Text
            }
            
            self.pm.save_profile(p_name, data)
            self.populate_all_combos()
            self.footing_profile_selector.SelectedItem = p_name
            forms.alert("Footing Profile Saved!")
        except Exception as ex: forms.alert("Error saving footing profile: " + str(ex))

    def delete_footing_profile_click(self, sender, e):
        sel_name = self.footing_profile_selector.SelectedItem
        if not sel_name or sel_name == "Default": return
        
        if forms.alert("Delete footing profile '{}'?".format(sel_name), yes=True, no=True):
            self.pm.delete_profile(sel_name)
            self.populate_all_combos()
            forms.alert("Footing Profile Deleted.")

    def draw_col_preview(self):
        self.col_preview_canvas.Children.Clear()
        
        try:
            cw_mm = float(self.col_width_ui.Text)
            cd_mm = float(self.col_depth_ui.Text)
            cov_mm = float(self.col_cover.Text)
        except: return

        # Scale Factor
        avail_w = 240.0
        avail_h = 200.0
        
        if cw_mm <= 0 or cd_mm <= 0: return
        
        scale_x = avail_w / cw_mm
        scale_y = avail_h / cd_mm
        scale = min(scale_x, scale_y) * 0.9 # 90% fit
        
        # Center dims
        draw_w = cw_mm * scale
        draw_h = cd_mm * scale
        off_x = (260 - draw_w)/2
        off_y = (220 - draw_h)/2
        
        # 1. Concrete (Gray)
        conc_rect = Shapes.Rectangle()
        conc_rect.Width = draw_w
        conc_rect.Height = draw_h
        conc_rect.Stroke = Brushes.Gray
        conc_rect.StrokeThickness = 2
        conc_rect.Fill = Brushes.WhiteSmoke
        Canvas.SetLeft(conc_rect, off_x)
        Canvas.SetTop(conc_rect, off_y)
        self.col_preview_canvas.Children.Add(conc_rect)
        
        # Helper to get dia in mm
        def get_dia_mm(name, is_stirrup=False):
            src = self.stirrup_types_data if is_stirrup else self.bar_types_data
            for n, d_ft in src:
                if n == str(name): return d_ft * 304.8
            return 10.0 # fallback

        # 2. Stirrup (Green)
        tie_n = self.col_tie_type.SelectedItem
        tie_d = get_dia_mm(tie_n, is_stirrup=True)
        
        # Inset by Cover
        st_w = max(0, cw_mm - 2*cov_mm) * scale
        st_h = max(0, cd_mm - 2*cov_mm) * scale
        st_x = off_x + cov_mm * scale
        st_y = off_y + cov_mm * scale
        
        if st_w > 0 and st_h > 0:
            st_rect = Shapes.Rectangle()
            st_rect.Width = st_w
            st_rect.Height = st_h
            st_rect.Stroke = Brushes.Green
            st_rect.StrokeThickness = max(tie_d * scale, 2.0)
            Canvas.SetLeft(st_rect, st_x)
            Canvas.SetTop(st_rect, st_y)
            self.col_preview_canvas.Children.Add(st_rect)
            
            # Corners
            def draw_circ(cx, cy, d_mm, color):
                dot = Shapes.Ellipse()
                dia_draw = max(d_mm * scale, 3.0)
                dot.Width = dia_draw
                dot.Height = dia_draw
                dot.Fill = color
                # cx, cy are relative to Canvas (0,0)
                Canvas.SetLeft(dot, cx - dia_draw/2)
                Canvas.SetTop(dot, cy - dia_draw/2)
                self.col_preview_canvas.Children.Add(dot)

            # Get Corner Dia
            corn_n = self.col_corner_type.SelectedItem
            corn_d = get_dia_mm(corn_n)
            
            # Get Side Dias
            sx_n = self.col_side_x_type.SelectedItem
            sx_d = get_dia_mm(sx_n)
            
            sy_n = self.col_side_y_type.SelectedItem
            sy_d = get_dia_mm(sy_n)

            # Inset from Edge to Center of Bar: Cover + Tie + Half Bar
            def get_inset(bar_d):
                 return (cov_mm + tie_d + bar_d/2) * scale
            
            # 4 Corners
            ins = get_inset(corn_d)
            corners = [
                (off_x + ins, off_y + ins),                  # TL
                (off_x + draw_w - ins, off_y + ins),         # TR
                (off_x + draw_w - ins, off_y + draw_h - ins),# BR
                (off_x + ins, off_y + draw_h - ins)          # BL
            ]
            
            for (cx, cy) in corners: draw_circ(cx, cy, corn_d, Brushes.Red)
            
            # Side Bars X (Top/Bot faces)
            try: qx = int(str(self.col_side_x_qty.SelectedItem))
            except: qx = 0
            
            if qx > 0:
                ins_x = get_inset(sx_d)
                # Correction: Side bars are between corners.
                # Corner centers are at 'corners'.
                # Side bars should be distributed BETWEEN them.
                # BUT, side bars might have different diameter -> different center inset?
                # Usually simplified to align with corners or align flush?
                # Let's align centers on the same stirrup line.
                # Stirrup line center is at: Cover + Tie_d/2.
                # So all bars center at: Cover + Tie_d + Bar_d/2? No, usually pressed against tie.
                # Yes: Cover + Tie_d + Bar_d/2.
                
                # Re-calc corner centers based on Side Bar Dia? No, Corner is Corner.
                # Let's verify loop logic.
                
                # Top Face
                # Corn TL to Corn TR
                # Actually, logic should be: Space between Cover+Tie (Inner stirrup face).
                # But for simplicity, let's interp between Corner Centers.
                x0, y0 = corners[0]
                x1, y1 = corners[1]
                step = (x1 - x0) / (qx + 1)
                for i in range(1, qx+1):
                    draw_circ(x0 + i*step, y0, sx_d, Brushes.Blue)
                
                # Bot Face
                x2, y2 = corners[3]
                x3, y3 = corners[2]
                step = (x3 - x2) / (qx + 1)
                for i in range(1, qx+1):
                    draw_circ(x2 + i*step, y2, sx_d, Brushes.Blue)
            
            # Side Bars Y (Left/Right faces)
            try: qy = int(str(self.col_side_y_qty.SelectedItem))
            except: qy = 0
            
            if qy > 0:
                # Left Face
                x0, y0 = corners[0]
                x3, y3 = corners[3]
                step = (y3 - y0) / (qy + 1)
                for i in range(1, qy+1):
                    draw_circ(x0, y0 + i*step, sy_d, Brushes.Blue)
                
                # Right Face
                x1, y1 = corners[1]
                x2, y2 = corners[2]
                step = (y2 - y1) / (qy + 1)
                for i in range(1, qy+1):
                    draw_circ(x1, y1 + i*step, sy_d, Brushes.Blue)

    def load_initial_profile(self):
        idx = self.profile_selector.Items.IndexOf("Default")
        if idx >= 0: self.profile_selector.SelectedIndex = idx
        elif self.profile_selector.Items.Count > 0: self.profile_selector.SelectedIndex = 0
        self.load_zone_ui_from_config(self.current_zone)

    def profile_changed(self, sender, e):
        p_name = self.profile_selector.SelectedItem
        if not p_name or p_name not in self.pm.profiles: return
        data = self.pm.profiles[p_name]
        g = data.get("Global", {})
        try:
            self.side_cover.Text = str(g.get("SideCover", 25))
            # self.end_offset.Text = str(g.get("EndOffset", 40)) # Removed
            self.end_spacing.Text = str(g.get("EndSpacing", 150))
            self.mid_spacing.Text = str(g.get("MidSpacing", 250))
            self.beam_width_ui.Text = str(g.get("BeamWidth", 300))
            self.beam_height_ui.Text = str(g.get("BeamHeight", 600))
            
            def set_cb(cb, val):
                if val:
                    i = cb.Items.IndexOf(str(val))
                    if i >= 0: cb.SelectedIndex = i
            
            # Legacy profile support: if Top/Bot missing, use BarType
            main_type = g.get("BarType")
            set_cb(self.top_bar_type_selector, g.get("TopBarType", main_type))
            set_cb(self.bot_bar_type_selector, g.get("BotBarType", main_type))
            
            set_cb(self.stirrup_selector, g.get("StirrupType"))
            
            # Unified Spacers
            set_cb(self.spacer_type, g.get("SpacerType", "None"))
            self.spacer_spacing.Text = str(g.get("SpacerSpacing", 1000))
            
            # Side Bars
            set_cb(self.beam_side_type, g.get("SideBarType", main_type))
            set_cb(self.beam_side_qty, str(g.get("SideBarQty", 0)))
            
            # Multi-Layer Support
            self.chk_top_same.IsChecked = g.get("TopSame", True)
            self.chk_bot_same.IsChecked = g.get("BotSame", True)
            set_cb(self.top_L2_type, g.get("TopL2Type", g.get("TopBarType", main_type)))
            set_cb(self.bot_L2_type, g.get("BotL2Type", g.get("BotBarType", main_type)))
            
            self.toggle_bar_types(None, None) # Refresh Visibility
            
        except: pass
        
        self.zone_configs["End Sections"] = data.get("End Sections", {"T1": 2, "T2": 0, "B1": 2, "B2": 0}).copy()
        self.zone_configs["Middle Section"] = data.get("Middle Section", {"T1": 2, "T2": 0, "B1": 2, "B2": 0}).copy()
        self.load_zone_ui_from_config(self.current_zone)
        self.calculate_all_zones()

    def save_profile_click(self, sender, e):
        from pyrevit.forms import ask_for_string
        name = ask_for_string(prompt="Enter Profile Name:", title="Save Profile")
        if not name: return
        self.update_zone_config_from_ui(self.current_zone)
        data = {
            "End Sections": self.zone_configs["End Sections"],
            "Middle Section": self.zone_configs["Middle Section"],
            "Global": {
                "SideCover": self.side_cover.Text,
                "EndOffset": self.side_cover.Text, # Unified: Use SideCover as EndOffset
                "EndSpacing": self.end_spacing.Text,
                "MidSpacing": self.mid_spacing.Text,
                "BeamWidth": self.beam_width_ui.Text,
                "BeamHeight": self.beam_height_ui.Text,
                "TopBarType": str(self.top_bar_type_selector.SelectedItem),
                "BotBarType": str(self.bot_bar_type_selector.SelectedItem),
                "BarType": str(self.top_bar_type_selector.SelectedItem), 
                "StirrupType": str(self.stirrup_selector.SelectedItem),
                "SpacerType": str(self.spacer_type.SelectedItem),
                "SpacerSpacing": self.spacer_spacing.Text,
                "SideBarType": str(self.beam_side_type.SelectedItem),
                "SideBarQty": str(self.beam_side_qty.SelectedItem),
                "TopSame": self.chk_top_same.IsChecked,
                "BotSame": self.chk_bot_same.IsChecked,
                "TopL2Type": str(self.top_L2_type.SelectedItem),
                "BotL2Type": str(self.bot_L2_type.SelectedItem)
            }
        }
        if self.pm.save_profile(name, data):
            if not self.profile_selector.Items.Contains(name): self.profile_selector.Items.Add(name)
            self.profile_selector.SelectedItem = name
            forms.alert("Profile Saved!")
        else: forms.alert("Error saving profile.")

    def delete_profile_click(self, sender, e):
        name = str(self.profile_selector.SelectedItem)
        if not name or name == "Default": 
            forms.alert("Cannot delete Default profile.")
            return

        from pyrevit import forms as pforms
        if pforms.alert("Delete profile '{}'?".format(name), yes=True, no=True):
            if self.pm.delete_profile(name):
                if self.profile_selector.Items.Contains(name):
                    self.profile_selector.Items.Remove(name)
                if self.profile_selector.Items.Count > 0:
                    self.profile_selector.SelectedIndex = 0
                forms.alert("Profile Deleted.")
            else:
                forms.alert("Error deleting profile.")

    def zone_input_changed(self, sender, e):
        self.update_zone_config_from_ui(self.current_zone)
        self.calculate_bars(self.current_zone)

    def global_input_changed(self, sender, e):
        try:
            self.beam_w_ft = float(self.beam_width_ui.Text) / 304.8
            self.beam_h_ft = float(self.beam_height_ui.Text) / 304.8
        except: pass
        self.calculate_all_zones()

    def toggle_bar_types(self, sender, e):
        # Sync types if "Same" is checked
        if self.chk_top_same.IsChecked:
             self.top_L2_type.SelectedIndex = self.top_bar_type_selector.SelectedIndex
        if self.chk_bot_same.IsChecked:
             self.bot_L2_type.SelectedIndex = self.bot_bar_type_selector.SelectedIndex
        
        # UI Visibility is handled via XAML Binding (Visibility="{Binding ...}")
        # But wait, IronPython + WPF Binding might need manual Refresh or just manual Visibility toggle
        from System.Windows import Visibility
        self.top_L2_type.Visibility = Visibility.Collapsed if self.chk_top_same.IsChecked else Visibility.Visible
        self.bot_L2_type.Visibility = Visibility.Collapsed if self.chk_bot_same.IsChecked else Visibility.Visible
        
        self.calculate_all_zones()

    def update_zone_config_from_ui(self, zone):
        def _q(cb):
            try: return int(str(cb.SelectedItem))
            except: return 0
        self.zone_configs[zone] = {
            "T1": _q(self.top_L1_qty), "T2": _q(self.top_L2_qty),
            "B1": _q(self.bot_L1_qty), "B2": _q(self.bot_L2_qty)
        }

    def load_zone_ui_from_config(self, zone):
        cfg = self.zone_configs.get(zone, {})
        self.top_L1_qty.SelectedItem = str(cfg.get("T1", 2))
        self.top_L2_qty.SelectedItem = str(cfg.get("T2", 0))
        self.bot_L1_qty.SelectedItem = str(cfg.get("B1", 2))
        self.bot_L2_qty.SelectedItem = str(cfg.get("B2", 0))

    def calculate_all_zones(self):
        for z in ["End Sections", "Middle Section"]: self.calculate_bars(z)

    def calculate_bars(self, zone_to_calc):
        try:
            ts = str(self.top_bar_type_selector.SelectedItem)
            ts2 = str(self.top_L2_type.SelectedItem) if not self.chk_top_same.IsChecked else ts
            
            bs = str(self.bot_bar_type_selector.SelectedItem)
            bs2 = str(self.bot_L2_type.SelectedItem) if not self.chk_bot_same.IsChecked else bs
            
            ss = str(self.stirrup_selector.SelectedItem)
            
            if not ts or not bs: return
            
            td = next((d[1] for d in self.bar_types_data if d[0] == ts), 0.02)
            td2 = next((d[1] for d in self.bar_types_data if d[0] == ts2), 0.02)
            
            bd = next((d[1] for d in self.bar_types_data if d[0] == bs), 0.02)
            bd2 = next((d[1] for d in self.bar_types_data if d[0] == bs2), 0.02)
            
            sd = next((d[1] for d in self.stirrup_types_data if d[0] == ss), 0.01) if ss else 0.01
            
            try: cov = float(self.side_cover.Text) / 304.8
            except: cov = 0.025 / 0.3048
            cfg = self.zone_configs[zone_to_calc]
            
            nb = []
            spacers = [] # (y_ft)
            
            # --- TOP BARS ---
            ew_t = float(self.beam_w_ft) - 2*cov - 2*sd - td
            if ew_t > 0:
                sx_t = -float(self.beam_w_ft)/2 + cov + sd + td/2
                
                def gl_t(qty, y):
                    if qty == 1: nb.append(RebarPoint(0, y, td, ts))
                    elif qty > 1:
                        sp = ew_t / (qty - 1)
                        for i in range(qty): nb.append(RebarPoint(sx_t + i * sp, y, td, ts))
                
                yt1 = float(self.beam_h_ft)/2 - cov - sd - td/2
                gl_t(cfg["T1"], yt1)
                
                # Top Spacers Calc
                if cfg["T2"] > 0:
                    yt2 = yt1 - td/2 - max(td, td2, 0.082) - td2/2
                    # Re-calc layout for Layer 2 if diameter different
                    ew_t2 = float(self.beam_w_ft) - 2*cov - 2*sd - td2
                    if ew_t2 > 0:
                        sx_t2 = -float(self.beam_w_ft)/2 + cov + sd + td2/2
                        def gl_t2(qty, y):
                            if qty == 1: nb.append(RebarPoint(0, y, td2, ts2))
                            elif qty > 1:
                                sp = ew_t2 / (qty - 1)
                                for i in range(qty): nb.append(RebarPoint(sx_t2 + i * sp, y, td2, ts2))
                        gl_t2(cfg["T2"], yt2)
                    
                    # Check spacer enabled
                    if str(self.spacer_type.SelectedItem) != "None":
                         spacers.append( (yt1 - td/2 - (max(td, td2, 0.082)/2.0)) )

            # --- BOTTOM BARS ---
            ew_b = float(self.beam_w_ft) - 2*cov - 2*sd - bd
            if ew_b > 0:
                sx_b = -float(self.beam_w_ft)/2 + cov + sd + bd/2
                
                def gl_b(qty, y):
                    if qty == 1: nb.append(RebarPoint(0, y, bd, bs))
                    elif qty > 1:
                        sp = ew_b / (qty - 1)
                        for i in range(qty): nb.append(RebarPoint(sx_b + i * sp, y, bd, bs))

                yb1 = -float(self.beam_h_ft)/2 + cov + sd + bd/2
                gl_b(cfg["B1"], yb1)
                
                # Bot Spacers Calc
                if cfg["B2"] > 0:
                    yb2 = yb1 + bd/2 + max(bd, bd2, 0.082) + bd2/2
                    # Re-calc layout for Layer 2 if diameter different
                    ew_b2 = float(self.beam_w_ft) - 2*cov - 2*sd - bd2
                    if ew_b2 > 0:
                        sx_b2 = -float(self.beam_w_ft)/2 + cov + sd + bd2/2
                        def gl_b2(qty, y):
                            if qty == 1: nb.append(RebarPoint(0, y, bd2, bs2))
                            elif qty > 1:
                                sp = ew_b2 / (qty - 1)
                                for i in range(qty): nb.append(RebarPoint(sx_b2 + i * sp, y, bd2, bs2))
                        gl_b2(cfg["B2"], yb2)
                    
                    # Check spacer enabled
                    if str(self.spacer_type.SelectedItem) != "None":
                         spacers.append( (yb1 + bd/2 + (max(bd, bd2, 0.082)/2.0)) )

            # --- SIDE BARS ---
            try:
                sq = int(str(self.beam_side_qty.SelectedItem))
                st_n = str(self.beam_side_type.SelectedItem)
                if st_n and sq > 0:
                    sid_d = next((d[1] for d in self.bar_types_data if d[0] == st_n), 0.01)
                    
                    s_inner_h = float(self.beam_h_ft) - 2*cov - 2*sd
                    
                    if s_inner_h > 0:
                         q_side = int(sq / 2.0)
                         step = s_inner_h / (q_side + 1)
                         y_start = -s_inner_h/2.0 + step
                         
                         x_off = float(self.beam_w_ft)/2.0 - cov - sd - sid_d/2.0
                         
                         for i in range(q_side):
                             loc_y = y_start + i*step
                             nb.append(RebarPoint(-x_off, loc_y, sid_d, st_n))
                             nb.append(RebarPoint(x_off, loc_y, sid_d, st_n))
            except: pass

            self.bars[zone_to_calc] = nb
            # We store spacers in a temporary view attribute or valid data struct?
            # For simplicity, let's attach to self.bars as a special key or just reuse a class var
            if zone_to_calc == self.current_zone: 
                self.current_spacers = spacers
                self.draw_ui()
            
        except: pass

    def setup_canvas(self):
        self.rebar_canvas.Width, self.rebar_canvas.Height = 300.0, 240.0
        aspect = float(self.beam_w_ft) / float(self.beam_h_ft)
        if aspect > (300.0/240.0): self.scale = 300.0 / float(self.beam_w_ft)
        else: self.scale = 240.0 / float(self.beam_h_ft)
            
    def draw_ui(self):
        self.rebar_canvas.Children.Clear()
        self.setup_canvas() # Dynamic Scale
        bw, bh = float(self.beam_w_ft) * self.scale, float(self.beam_h_ft) * self.scale
        cx, cy = 150.0, 120.0
        
        # Main Beam Rect
        rect = Rectangle()
        rect.Width, rect.Height = bw, bh
        rect.Stroke, rect.StrokeThickness = Brushes.Black, 2
        rect.Fill = SolidColorBrush(Color.FromArgb(15, 0, 0, 0))
        Canvas.SetLeft(rect, cx - bw/2)
        Canvas.SetTop(rect, cy - bh/2)
        self.rebar_canvas.Children.Add(rect)
        
        # Stirrup Rect
        stirrup_inner_w = 0 # store for spacer drawing
        try:
            cov = float(self.side_cover.Text) / 304.8
            sw, sh = bw - 2*cov*self.scale, bh - 2*cov*self.scale
            stirrup_inner_w = sw
            
            # Get current Stirrup Diameter for dynamic thickness
            ss = str(self.stirrup_selector.SelectedItem)
            sd = next((d[1] for d in self.stirrup_types_data if d[0] == ss), 0.01) if ss else 0.01
            # Scale diameter to pixels
            stroke_thk = max(sd * self.scale, 2.0) # Min 2px
            
            if sw > 0 and sh > 0:
                s_rect = Rectangle()
                s_rect.Width, s_rect.Height = sw, sh
                s_rect.Stroke = Brushes.Red
                s_rect.StrokeThickness = stroke_thk
                
                Canvas.SetLeft(s_rect, cx - sw/2)
                Canvas.SetTop(s_rect, cy - sh/2)
                self.rebar_canvas.Children.Add(s_rect)
        except: pass
        
        # Spacers (Draw before bars so they are behind?)
        if hasattr(self, 'current_spacers') and stirrup_inner_w > 0:
            for sy in self.current_spacers:
                # Draw Line
                l = Rectangle()
                l.Width = stirrup_inner_w
                l.Height = 2 # Thinner visual
                l.Fill = Brushes.Green 
                Canvas.SetLeft(l, cx - stirrup_inner_w/2)
                Canvas.SetTop(l, cy - sy * self.scale - 1)
                self.rebar_canvas.Children.Add(l)
        
        # Bars
        for rb in self.bars.get(self.current_zone, []):
            dia = max(rb.diameter_ft * self.scale, 4)
            ell = Ellipse()
            ell.Width = ell.Height = dia
            ell.Fill, ell.Stroke, ell.StrokeThickness = Brushes.SteelBlue, Brushes.White, 1
            Canvas.SetLeft(ell, cx + rb.lx * self.scale - dia/2)
            Canvas.SetTop(ell, cy - rb.ly * self.scale - dia/2)
            # Add Tooltip
            ell.ToolTip = rb.type_name
            self.rebar_canvas.Children.Add(ell)

    def switch_zone_click(self, sender, e):
        self.update_zone_config_from_ui(self.current_zone)
        self.current_zone = "Middle Section" if "End" in self.current_zone else "End Sections"
        self.update_zoning_info()
        self.load_zone_ui_from_config(self.current_zone)
        self.calculate_bars(self.current_zone) # Recalc visuals

    def update_zoning_info(self):
        self.zone_title.Text = "Editing: " + self.current_zone
        self.switch_zone_btn.Content = "Switch to " + ("End Sections" if "Middle" in self.current_zone else "Middle Section")

    def submit_click(self, sender, e): 
        self.selected_tab_index = self.main_tab_control.SelectedIndex
        self.DialogResult = True
        self.Close()

# --- XAML ---
xaml_content = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Structural Rebar Designer" Height="700" Width="850" WindowStartupLocation="CenterScreen">
    <TabControl x:Name="main_tab_control" Margin="5">
        <!-- BEAM REBAR TAB -->
        <TabItem Header="Beam Rebar">
            <Grid Margin="10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="320"/> <!-- Left: Geometry/Preview -->
                    <ColumnDefinition Width="*"/>   <!-- Right: Settings -->
                </Grid.ColumnDefinitions>

                <!-- LEFT COLUMN -->
                <StackPanel Grid.Column="0" Margin="0,0,15,0">
                    <TextBlock Text="Beam Rebar Designer" FontSize="20" FontWeight="Bold" Margin="0,0,0,15" Foreground="#333"/>
                    
                     <!-- Beam Dimensions -->
                    <GroupBox Header="Design Beam Size (mm)" Margin="0,0,0,15" Padding="5">
                        <Grid>
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                            <StackPanel Margin="0,0,5,0"><TextBlock Text="Width (b):"/><TextBox x:Name="beam_width_ui" Text="300" Padding="2"/></StackPanel>
                            <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Height (h):"/><TextBox x:Name="beam_height_ui" Text="600" Padding="2"/></StackPanel>
                        </Grid>
                    </GroupBox>

                    <!-- Preview Canvas -->
                     <Border Background="#FAFAFA" BorderBrush="#DDD" BorderThickness="1" CornerRadius="5" Padding="10" Margin="0,0,0,15">
                        <StackPanel>
                            <Grid Margin="0,0,0,5">
                                <TextBlock x:Name="zone_title" FontWeight="Bold" VerticalAlignment="Center"/>
                                <Button x:Name="switch_zone_btn" HorizontalAlignment="Right" Click="switch_zone_click" Padding="8,2" FontSize="10" Content="Switch Zone"/>
                            </Grid>
                            <Canvas x:Name="rebar_canvas" Width="280" Height="220" HorizontalAlignment="Center" Background="Transparent"/>
                        </StackPanel>
                    </Border>

                     <!-- Spacings -->
                     <GroupBox Header="Geometry Settings (mm)" Margin="0,0,0,0" Padding="5">
                        <Grid>
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                            
                            <StackPanel Grid.Column="0" Margin="0,0,5,0"><TextBlock Text="Cover (Side &amp; End):"/><TextBox x:Name="side_cover" Text="25" Padding="2"/></StackPanel>
                        </Grid>
                    </GroupBox>
                </StackPanel>

                <!-- RIGHT COLUMN -->
                <ScrollViewer Grid.Column="1" VerticalScrollBarVisibility="Auto">
                    <StackPanel Margin="5,0,0,0">
                         <!-- Profile Manager -->
                        <Grid Margin="0,0,0,15">
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                            <StackPanel Grid.Column="0"><TextBlock Text="Profile:" FontWeight="SemiBold"/><ComboBox x:Name="profile_selector" Margin="0,2,5,0"/></StackPanel>
                            <Button x:Name="save_profile_btn" Content="Save" Grid.Column="1" Padding="15,0" VerticalAlignment="Bottom" Height="26" Margin="0,0,5,0"/>
                            <Button x:Name="delete_profile_btn" Content="Del" Grid.Column="2" Padding="10,0" VerticalAlignment="Bottom" Height="26" Background="#FFDDDD" BorderBrush="#FFAAAA"/>
                        </Grid>

                        <StackPanel Margin="0,0,0,15">
                            <TextBlock Text="Stirrup Bar Type:" Margin="0,0,0,2" FontWeight="SemiBold"/>
                            <ComboBox x:Name="stirrup_selector" Padding="4"/>
                        </StackPanel>

                        <Grid Margin="0,0,0,15">
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                            <StackPanel Grid.Column="0" Margin="0,0,5,0"><TextBlock Text="End Spacing:"/><TextBox x:Name="end_spacing" Text="150" Padding="2"/></StackPanel>
                            <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Mid Spacing:"/><TextBox x:Name="mid_spacing" Text="250" Padding="2"/></StackPanel>
                        </Grid>

                        <CheckBox x:Name="chk_continuity" Content="Auto-Detect Continuity" IsChecked="True" Margin="0,0,0,10" FontWeight="Bold"/>
                        <GroupBox Header="Main Bars Configuration" Margin="0,0,0,15" Padding="5">
                            <Grid Margin="0,5">
                                <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="1.2*"/></Grid.ColumnDefinitions>
                                <Grid.RowDefinitions>
                                    <RowDefinition Height="Auto"/> <RowDefinition Height="Auto"/> <RowDefinition Height="Auto"/>
                                    <RowDefinition Height="15"/>
                                    <RowDefinition Height="Auto"/> <RowDefinition Height="Auto"/> <RowDefinition Height="Auto"/>
                                </Grid.RowDefinitions>
                                
                                <TextBlock Grid.Row="0" Grid.Column="0" Text="TOP" FontWeight="Bold" VerticalAlignment="Center" Margin="0,0,10,5" Foreground="#0055AA"/>
                                <StackPanel Grid.Row="0" Grid.Column="1" Grid.ColumnSpan="2" Orientation="Horizontal">
                                    <ComboBox x:Name="top_bar_type_selector" Width="120" Margin="0,0,5,5"/>
                                    <CheckBox x:Name="chk_top_same" Content="Same for all layers" IsChecked="True" VerticalAlignment="Center" Margin="5,0,0,5"/>
                                </StackPanel>

                                <TextBlock Grid.Row="1" Grid.Column="0" Text="Outer (L1):" VerticalAlignment="Center" Margin="10,0,5,2"/>
                                <ComboBox x:Name="top_L1_qty" Grid.Row="1" Grid.Column="1" Margin="0,2"/>
                                
                                <TextBlock Grid.Row="2" Grid.Column="0" Text="Inner (L2):" VerticalAlignment="Center" Margin="10,0,5,2"/>
                                <StackPanel Grid.Row="2" Grid.Column="1" Grid.ColumnSpan="2" Orientation="Horizontal">
                                    <ComboBox x:Name="top_L2_qty" Width="60" Margin="0,2,5,2"/>
                                    <ComboBox x:Name="top_L2_type" Width="100" Margin="5,2,0,2"/>
                                </StackPanel>
                                
                                <TextBlock Grid.Row="4" Grid.Column="0" Text="BOTTOM" FontWeight="Bold" VerticalAlignment="Center" Margin="0,0,10,5" Foreground="#0055AA"/>
                                <StackPanel Grid.Row="4" Grid.Column="1" Grid.ColumnSpan="2" Orientation="Horizontal">
                                    <ComboBox x:Name="bot_bar_type_selector" Width="120" Margin="0,0,5,5"/>
                                    <CheckBox x:Name="chk_bot_same" Content="Same for all layers" IsChecked="True" VerticalAlignment="Center" Margin="5,0,0,5"/>
                                </StackPanel>

                                <TextBlock Grid.Row="5" Grid.Column="0" Text="Outer (L1):" VerticalAlignment="Center" Margin="10,0,5,2"/>
                                <ComboBox x:Name="bot_L1_qty" Grid.Row="5" Grid.Column="1" Margin="0,2"/>
                                
                                <TextBlock Grid.Row="6" Grid.Column="0" Text="Inner (L2):" VerticalAlignment="Center" Margin="10,0,5,2"/>
                                <StackPanel Grid.Row="6" Grid.Column="1" Grid.ColumnSpan="2" Orientation="Horizontal">
                                    <ComboBox x:Name="bot_L2_qty" Width="60" Margin="0,2,5,2"/>
                                    <ComboBox x:Name="bot_L2_type" Width="100" Margin="5,2,0,2"/>
                                </StackPanel>
                            </Grid>
                        </GroupBox>

                        <GroupBox Header="Spacer Bars" Margin="0,0,0,20" Padding="5">
                            <Grid>
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <StackPanel Grid.Column="0" Margin="0,0,5,0">
                                    <TextBlock Text="Type:" Margin="0,0,0,2"/>
                                    <ComboBox x:Name="spacer_type"/>
                                </StackPanel>
                                <StackPanel Grid.Column="1" Margin="5,0,0,0">
                                    <TextBlock Text="Spacing (mm):" Margin="0,0,0,2"/>
                                    <TextBox x:Name="spacer_spacing" Text="1000" Padding="2"/>
                                </StackPanel>
                            </Grid>
                        </GroupBox>

                        <GroupBox Header="Side Bars (Skin Reinforcement)" Margin="0,0,0,15" Padding="5">
                             <Grid>
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <StackPanel Grid.Column="0" Margin="0,0,5,0">
                                    <TextBlock Text="Type:" Margin="0,0,0,2"/>
                                    <ComboBox x:Name="beam_side_type"/>
                                </StackPanel>
                                <StackPanel Grid.Column="1" Margin="5,0,0,0">
                                    <TextBlock Text="Total Qty:" Margin="0,0,0,2"/>
                                    <ComboBox x:Name="beam_side_qty"/>
                                </StackPanel>
                            </Grid>
                        </GroupBox>
                        
                        <Button Content="Create Beam Rebar" Height="45" Click="submit_click" Background="#007ACC" Foreground="White" FontWeight="Bold" FontSize="14" Cursor="Hand"/>
                    </StackPanel>
                </ScrollViewer>
            </Grid>
        </TabItem>

        <!-- COLUMN REBAR TAB -->
        <TabItem Header="Column Rebar">
            <Grid Margin="10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="300"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <!-- Left: Geometry -->
                <StackPanel Grid.Column="0" Margin="0,0,20,0">
                     <TextBlock Text="Column Rebar Designer" FontSize="20" FontWeight="Bold" Margin="0,0,0,15" Foreground="#333"/>
                     
                     <GroupBox Header="Column Size (mm)" Margin="0,0,0,15" Padding="5">
                        <Grid>
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                            <StackPanel Margin="0,0,5,0"><TextBlock Text="Width (X):"/><TextBox x:Name="col_width_ui" Text="400" Padding="2"/></StackPanel>
                            <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Depth (Y):"/><TextBox x:Name="col_depth_ui" Text="400" Padding="2"/></StackPanel>
                        </Grid>
                    </GroupBox>
                    
                    <!-- Column Preview -->
                    <Border Background="#FAFAFA" BorderBrush="#DDD" BorderThickness="1" CornerRadius="5" Padding="10" Margin="0,0,0,15">
                         <Canvas x:Name="col_preview_canvas" Width="260" Height="220" HorizontalAlignment="Center" Background="Transparent"/>
                    </Border>
                    
                    <GroupBox Header="Cover &amp; Stirrups" Margin="0,0,0,15" Padding="5">
                        <StackPanel>
                             <Grid Margin="0,0,0,10">
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <StackPanel Margin="0,0,5,0"><TextBlock Text="Cover:"/><TextBox x:Name="col_cover" Text="25" Padding="2"/></StackPanel>
                                <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="End Spacing:"/><TextBox x:Name="col_tie_spacing_end" Text="100" Padding="2"/></StackPanel>
                            </Grid>
                            <Grid Margin="0,0,0,10">
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <StackPanel Margin="0,0,5,0"><TextBlock Text="Mid Spacing:"/><TextBox x:Name="col_tie_spacing_mid" Text="200" Padding="2"/></StackPanel>
                                <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Conf. Height:"/><TextBox x:Name="col_conf_height" Text="600" Padding="2"/></StackPanel>
                            </Grid>
                            <Grid>
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <StackPanel Grid.Column="0" Margin="0,0,5,0"><TextBlock Text="Tie Bar Type:" /><ComboBox x:Name="col_tie_type"/></StackPanel>
                            </Grid>
                        </StackPanel>
                    </GroupBox>
                </StackPanel>

                <!-- Right: Vertical Bars -->
                <ScrollViewer Grid.Column="1" VerticalScrollBarVisibility="Auto">
                    <StackPanel>
                        <!-- Column Profile Manager -->
                        <Grid Margin="0,0,0,15">
                            <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
                            <StackPanel Grid.Column="0"><TextBlock Text="Profile:" FontWeight="SemiBold"/><ComboBox x:Name="col_profile_selector" Margin="0,2,5,0"/></StackPanel>
                            <Button x:Name="save_col_profile_btn" Content="Save" Grid.Column="1" Padding="15,0" VerticalAlignment="Bottom" Height="26" Margin="0,0,5,0"/>
                            <Button x:Name="del_col_profile_btn" Content="Del" Grid.Column="2" Padding="10,0" VerticalAlignment="Bottom" Height="26" Background="#FFDDDD" BorderBrush="#FFAAAA"/>
                        </Grid>

                        <GroupBox Header="Vertical Reinforcement" Padding="10" Margin="0,0,0,15">
                            <StackPanel>
                                <!-- Corner Bars -->
                                <TextBlock Text="Corner Bars (4x):" FontWeight="Bold" Margin="0,0,0,5"/>
                                <ComboBox x:Name="col_corner_type" Margin="0,0,0,15"/>
                                
                                <!-- X-Face Side Bars -->
                                <TextBlock Text="X-Face Side Bars (Total for 2 faces):" FontWeight="Bold" Margin="0,0,0,5"/>
                                <Grid Margin="0,0,0,10">
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Grid.Column="0" Margin="0,0,5,0"><TextBlock Text="Type:"/><ComboBox x:Name="col_side_x_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Qty (per face):"/><ComboBox x:Name="col_side_x_qty"/></StackPanel>
                                </Grid>
                                
                                <!-- Y-Face Side Bars -->
                                <TextBlock Text="Y-Face Side Bars (Total for 2 faces):" FontWeight="Bold" Margin="0,0,0,5"/>
                                <Grid>
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Margin="0,0,5,0"><TextBlock Text="Type:"/><ComboBox x:Name="col_side_y_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Qty (per face):"/><ComboBox x:Name="col_side_y_qty"/></StackPanel>
                                </Grid>

                                <StackPanel Margin="0,10,0,0">
                                    <CheckBox x:Name="chk_col_anchorage" Content="Anchor Vertical Bars to Foundation" IsChecked="False" FontWeight="Bold" Margin="0,0,0,10"/>
                                    <TextBlock Text="Top Extension (mm):" FontWeight="Bold"/>
                                    <TextBox x:Name="col_top_extension" Text="0" Padding="2"/>
                                </StackPanel>
                            </StackPanel>
                        </GroupBox>

                        <Button Content="Create Column Rebar" Height="50" Click="submit_click" Background="#28a745" Foreground="White" FontWeight="Bold" FontSize="15" Cursor="Hand"/>
                    </StackPanel>
                </ScrollViewer>
            </Grid>
        </TabItem>

        <!-- FOOTING REBAR TAB -->
        <TabItem Header="Footing Rebar">
            <Grid Margin="10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="300"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <!-- Left: Geometry -->
                <StackPanel Grid.Column="0" Margin="0,0,20,0">
                    <TextBlock Text="Footing Rebar Designer" FontSize="20" FontWeight="Bold" Margin="0,0,0,15" Foreground="#333"/>
                    
                    <GroupBox Header="Footing Information" Margin="0,0,0,15" Padding="5">
                         <StackPanel>
                            <TextBlock x:Name="footing_info_text" Text="Select a footing to see dimensions." TextWrapping="Wrap" Margin="0,0,0,5" Foreground="#666"/>
                            <TextBlock x:Name="footing_dims_label" FontWeight="Bold"/>
                         </StackPanel>
                    </GroupBox>
                    
                    <GroupBox Header="Profile Manager" Margin="0,0,0,15" Padding="5">
                        <StackPanel>
                            <TextBlock Text="Select Profile:"/>
                            <ComboBox x:Name="footing_profile_selector" Margin="0,0,0,5"/>
                            <Grid>
                                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                <Button x:Name="save_footing_profile_btn" Content="Save" Margin="0,0,2,0"/>
                                <Button x:Name="del_footing_profile_btn" Grid.Column="1" Content="Delete" Margin="2,0,0,0"/>
                            </Grid>
                        </StackPanel>
                    </GroupBox>
                    
                    <GroupBox Header="General Settings" Margin="0,0,0,15" Padding="5">
                        <StackPanel>
                            <TextBlock Text="Concrete Cover (mm):"/>
                            <TextBox x:Name="footing_cover" Text="50" Padding="2" Margin="0,0,0,10"/>
                            <CheckBox x:Name="chk_footing_top_mat" Content="Include Top Reinforcement Mat" FontWeight="Bold"/>
                        </StackPanel>
                    </GroupBox>
                </StackPanel>

                <!-- Right: Reinforcement -->
                <ScrollViewer Grid.Column="1" VerticalScrollBarVisibility="Auto">
                    <StackPanel>
                        <GroupBox Header="Bottom Mat Reinforcement" Padding="10" Margin="0,0,0,15">
                            <StackPanel>
                                <TextBlock Text="X-Direction (Primary):" FontWeight="Bold" Margin="0,0,0,5"/>
                                <Grid Margin="0,0,0,10">
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Margin="0,0,5,0"><TextBlock Text="Type:"/><ComboBox x:Name="footing_bx_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Spacing (mm):"/><TextBox x:Name="footing_bx_spacing" Text="200" Padding="2"/></StackPanel>
                                </Grid>
                                
                                <TextBlock Text="Y-Direction (Secondary):" FontWeight="Bold" Margin="0,0,0,5"/>
                                <Grid>
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Margin="0,0,5,0"><TextBlock Text="Type:"/><ComboBox x:Name="footing_by_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Spacing (mm):"/><TextBox x:Name="footing_by_spacing" Text="200" Padding="2"/></StackPanel>
                                </Grid>
                            </StackPanel>
                        </GroupBox>

                        <GroupBox Header="Top Mat Reinforcement (If Enabled)" Padding="10" Margin="0,0,0,15" IsEnabled="{Binding ElementName=chk_footing_top_mat, Path=IsChecked}">
                            <StackPanel>
                                <Grid Margin="0,0,0,10">
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Margin="0,0,5,0"><TextBlock Text="X-Type:"/><ComboBox x:Name="footing_tx_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Spacing:"/><TextBox x:Name="footing_tx_spacing" Text="200" Padding="2"/></StackPanel>
                                </Grid>
                                <Grid>
                                    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                                    <StackPanel Margin="0,0,5,0"><TextBlock Text="Y-Type:"/><ComboBox x:Name="footing_ty_type"/></StackPanel>
                                    <StackPanel Grid.Column="1" Margin="5,0,0,0"><TextBlock Text="Spacing:"/><TextBox x:Name="footing_ty_spacing" Text="200" Padding="2"/></StackPanel>
                                </Grid>
                            </StackPanel>
                        </GroupBox>

                        <Button Content="Create Footing Rebar" Height="50" Click="submit_click" Background="#6f42c1" Foreground="White" FontWeight="Bold" FontSize="15" Cursor="Hand"/>
                    </StackPanel>
                </ScrollViewer>
            </Grid>
        </TabItem>

        <!-- SECTIONS TAB -->
        <TabItem Header="Create Sections">
            <Grid Margin="10">
                <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
                
                <GroupBox Header="Beam Sections" Margin="0,0,0,15" Padding="10">
                    <StackPanel>
                        <TextBlock Text="Generates sections at Support (L/6) and Mid-span (L/2)." TextWrapping="Wrap" Margin="0,0,0,10"/>
                        <CheckBox x:Name="chk_dims_beam" Content="Automate Dimensions" IsChecked="True" Margin="0,0,0,10"/>
                        
                        <!-- Custom Option -->
                        <CheckBox x:Name="chk_beam_custom" Content="Custom Locations (Ratio 0-1)" Margin="0,0,0,5"/>
                        <TextBox x:Name="txt_beam_locs" Text="0.25, 0.5, 0.75" Margin="0,0,0,10" IsEnabled="{Binding ElementName=chk_beam_custom, Path=IsChecked}"/>

                        <Button Content="Select Beams &amp; Create" Height="30" Click="sec_beam_click" Background="#DDDDDD"/>
                    </StackPanel>
                </GroupBox>

                <GroupBox Grid.Row="1" Header="Column Sections" Padding="10">
                     <StackPanel>
                        <TextBlock Text="Generates cross-section at Mid-height." TextWrapping="Wrap" Margin="0,0,0,10"/>
                        <CheckBox x:Name="chk_dims_col" Content="Automate Dimensions" IsChecked="True" Margin="0,0,0,10"/>
                        
                        <!-- Custom Option -->
                        <CheckBox x:Name="chk_col_custom" Content="Custom Locations (Ratio 0-1)" Margin="0,0,0,5"/>
                        <TextBox x:Name="txt_col_locs" Text="0.5" Margin="0,0,0,10" IsEnabled="{Binding ElementName=chk_col_custom, Path=IsChecked}"/>

                        <Button Content="Select Columns &amp; Create" Height="30" Click="sec_col_click" Background="#DDDDDD"/>
                    </StackPanel>
                </GroupBox>
            </Grid>
        </TabItem>
    </TabControl>
</Window>
"""

def create_rebar():
    doc = revit.doc
    try:
        # Check and ensure 6mm and 8mm exist
        def ensure_bar_type(name, dia_mm):
            bts = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarBarType).ToElements()
            for b in bts:
                # Safe Name Access
                bn = b.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                if not bn:
                    try: bn = b.Name
                    except: pass
                if bn == name or bn == str(name) + "mm": return b
            
            # Create if missing (Duplicate first one)
            if bts:
                with revit.Transaction("Create Rebar Type " + name):
                    new_t = bts[0].Duplicate(name)
                    new_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).Set(dia_mm / 304.8)
                    return new_t
            return None

        # Auto-create common sizes if missing
        ensure_bar_type("6mm", 6)
        ensure_bar_type("8mm", 8)
        ensure_bar_type("10mm", 10)
        ensure_bar_type("12mm", 12)

        bts = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarBarType).ToElements()
        bt_data = []
        for b in bts:
            n = b.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or b.Name
            d = 0.04
            try: d = b.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
            except: pass
            bt_data.append((n, d))
        # Sort by Name for better UI
        bt_data.sort(key=lambda x: x[0])

        if not bt_data: return forms.alert("No Rebar Types")

        # Hook Helper
        def get_hook_names(doc):
            hooks = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarHookType).ToElements()
            names = []
            for h in hooks:
                try: names.append(h.Name)
                except:
                    p = h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                    if p: names.append(p.AsString())
            return sorted(list(set(names))) # Unique and sorted

        hook_names = get_hook_names(doc)

        def find_t(name):
            n_ = str(name)
            for t in bts:
                nt = t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or t.Name
                if nt == n_: return t
            return None
        
        pm = ProfileManager(doc)
        temp = os.path.join(os.environ['TEMP'], 'beamrebar_v5.xaml')
        with open(temp, 'w') as f: f.write(xaml_content)
        
        win = ParametricRebarWindow(temp) 
        win.setup_data(bt_data, bt_data, pm)
        

        if not win.show_dialog(): return
        
        sel_idx = win.selected_tab_index
        if sel_idx == 3: return # Sections tab handled internally

        # PICK BEAMS
        filt = BeamSelectionFilter()
        beams = []
        prompt = "Select Elements"
        if sel_idx == 0: prompt = "Select Beams"
        elif sel_idx == 1: prompt = "Select Columns"
        elif sel_idx == 2: prompt = "Select Footings"
        try:
            refs = revit.uidoc.Selection.PickObjects(ObjectType.Element, filt, prompt)
            for r in refs: beams.append(doc.GetElement(r))
        except: return
        if not beams: return forms.alert("No Beams selected.")

        # VALIDATION & PARAMS
        def get_beam_dims_geometric(b):
            # Returns: width, height, center_y, center_z
            w_val, h_val = 0.0, 0.0
            s = b.Symbol
            
            def _get_val(e, names):
                for n in names:
                    p = e.LookupParameter(n)
                    if p and p.HasValue: return p.AsDouble()
                return None
            
            # Param Search
            # Common: b, h, Width, Height, Beam Width, Beam Height, BF, D, B, H
            w_names = ["b", "Width", "Beam Width", "BF", "B", "Width (b)"]
            h_names = ["h", "Height", "Beam Height", "D", "Depth", "H", "Height (h)"]
            
            w_val = _get_val(s, w_names) or _get_val(b, w_names)
            h_val = _get_val(s, h_names) or _get_val(b, h_names)
            
            cy, cz = 0.0, 0.0
            
            try:
                opt = DB.Options()
                opt.ComputeReferences = True
                opt.DetailLevel = DB.ViewDetailLevel.Fine
                geom = b.get_Geometry(opt)
                
                def get_solids(g_elem):
                    sols = []
                    for g in g_elem:
                        if isinstance(g, DB.Solid) and g.Volume > 0:
                            sols.append(g)
                        elif isinstance(g, DB.GeometryInstance):
                            sols.extend(get_solids(g.GetInstanceGeometry()))
                    return sols

                all_solids = get_solids(geom)
                if all_solids:
                    best_solid = max(all_solids, key=lambda s: s.Volume)
                    
                    # 1. Centroid for Alignment
                    centroid = best_solid.ComputeCentroid()
                    trans = b.GetTransform()
                    inv_trans = trans.Inverse
                    local_c = inv_trans.OfPoint(centroid)
                    cy = local_c.Y
                    cz = local_c.Z
                    
                    # 2. Fallback Dimensions from BoundingBox if Params Failed
                    if not w_val or not h_val:
                        # Get Local Bounding Box of the Solid
                        # Transform all vertices to local space
                        min_y, max_y = 99999.0, -99999.0
                        min_z, max_z = 99999.0, -99999.0
                        
                        for edge in best_solid.Edges:
                             pts = edge.Tessellate()
                             for p in pts:
                                 local_p = inv_trans.OfPoint(p)
                                 if local_p.Y < min_y: min_y = local_p.Y
                                 if local_p.Y > max_y: max_y = local_p.Y
                                 if local_p.Z < min_z: min_z = local_p.Z
                                 if local_p.Z > max_z: max_z = local_p.Z
                        
                        if not w_val: w_val = max_y - min_y
                        if not h_val: h_val = max_z - min_z

            except Exception as e: 
                print("Geometry/Param Warning: " + str(e))
            
            # Final Safety
            if w_val is None: w_val = 0.0
            if h_val is None: h_val = 0.0
            
            return w_val, h_val, cy, cz

        ref_w, ref_h, _, _ = get_beam_dims_geometric(beams[0])
        
        if ref_w is None: return forms.alert("Could not get beam dimensions. Ensure the family is rectangular.")
        for b in beams:
            w, h, _, _ = get_beam_dims_geometric(b)
            if not w or abs(w-ref_w)>0.001 or abs(h-ref_h)>0.001: return forms.alert("Selected beams must have identical sizes!")

        es, ms = float(win.end_spacing.Text)/304.8, float(win.mid_spacing.Text)/304.8
        cov = float(win.side_cover.Text)/304.8
        off = cov # Unified Cover
        
        st_t = find_t(win.stirrup_selector.SelectedItem)
        top_bt_t = find_t(win.top_bar_type_selector.SelectedItem)
        bot_bt_t = find_t(win.bot_bar_type_selector.SelectedItem)
        
        # Spacers (Unified)
        sp_name = str(win.spacer_type.SelectedItem)
        sp_t = find_t(sp_name) if sp_name != "None" else None
        
        try:
            sp_s = float(win.spacer_spacing.Text) / 304.8
        except:
             sp_s = 1000.0/304.8
             
        # Side Bars
        side_n = str(win.beam_side_type.SelectedItem)
        if side_n:
             side_t = find_t(side_n)
        else: side_t = None
        
        try: side_q = int(str(win.beam_side_qty.SelectedItem))
        except: side_q = 0
             
        if not st_t or not top_bt_t or not bot_bt_t: return forms.alert("Selected Rebar Types not found")

        # Hook Helper
        def get_hook(doc):
             # Try to find a 135 degree hook, else 90, else any
             hooks = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarHookType).ToElements()
             
             def get_n(h):
                 # Safe name retrieval
                 try: return h.Name
                 except: 
                     p = h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                     return p.AsString() if p else ""

             h135 = next((h for h in hooks if "135" in get_n(h)), None)
             if h135: return h135
             h90 = next((h for h in hooks if "90" in get_n(h)), None)
             if h90: return h90
             return hooks[0] if hooks else None
             
        hook_t = get_hook(doc)
        
        # 90 Deg Hook for Mains
        def get_hook_90(doc):
             hooks = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarHookType).ToElements()
             h90 = next((h for h in hooks if "90" in (h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or h.Name)), None)
             return h90

        # hk90 = get_hook_90(doc) # Removed as per instruction

        # Helper for Sets
        class RebarSetDef:
            def __init__(self, y_local, qty, type_name, bar_dia, array_len=0, start_x_local=0, layer_tag=""):
                self.y_local = y_local
                self.qty = qty
                self.type_name = type_name
                self.bar_dia = bar_dia
                self.array_len = array_len
                self.start_x_local = start_x_local
                self.layer_tag = layer_tag

        def get_supports_at_ends(beam):
            # Returns (start_elem, end_elem)
            # Uses Bounding Box Intersects filter at endpoints
            c = beam.Location.Curve
            p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
            
            def find_supp(pt):
                # Search small box around pt
                d = 0.5 # ft?
                outline = DB.Outline(pt - DB.XYZ(d,d,d), pt + DB.XYZ(d,d,d))
                filt = DB.BoundingBoxIntersectsFilter(outline)
                ids = DB.FilteredElementCollector(doc).WherePasses(filt).ToElementIds()
                for i in ids:
                    if i == beam.Id: continue
                    el = doc.GetElement(i)
                    if not el: continue
                    cat = el.Category.Id.IntegerValue
                    if cat == COLUMN_CAT_ID: return el, "Column"
                    if cat == FRAMING_CAT_ID: return el, "Beam"
                return None, "None"
            
            s0, t0 = find_supp(p0)
            s1, t1 = find_supp(p1)
            return (s0, t0), (s1, t1)

        debug_log = []
        def log(msg): debug_log.append(msg)

        # ----------------------
        # BEAM LOGIC
        # ----------------------
        def get_rebar_sets(z_name, bw, bh, skip_t1=False, skip_b1=False, skip_t2=False, skip_b2=False):
            cfg = win.zone_configs.get(z_name, {})
            sets = []
            spacers = []
            
            # Diameters
            sd = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
            md_t = top_bt_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
            md_t2 = find_t(win.top_L2_type.SelectedItem).get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble() if not win.chk_top_same.IsChecked else md_t
            
            md_b = bot_bt_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
            md_b2 = find_t(win.bot_L2_type.SelectedItem).get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble() if not win.chk_bot_same.IsChecked else md_b
            
            # Widths
            ew_t = bw - 2*cov - 2*sd - md_t
            sx_t = -bw/2.0 + cov + sd + md_t/2.0
            
            ew_t2 = bw - 2*cov - 2*sd - md_t2
            sx_t2 = -bw/2.0 + cov + sd + md_t2/2.0
            
            ew_b = bw - 2*cov - 2*sd - md_b
            sx_b = -bw/2.0 + cov + sd + md_b/2.0
            
            ew_b2 = bw - 2*cov - 2*sd - md_b2
            sx_b2 = -bw/2.0 + cov + sd + md_b2/2.0
            
            # T1
            q = cfg.get("T1", 0)
            if q > 0 and not skip_t1:
                y = bh/2.0 - cov - sd - md_t/2.0
                sets.append(RebarSetDef(y, q, str(win.top_bar_type_selector.SelectedItem), md_t, ew_t, sx_t, "T1"))
            
            # B1
            q = cfg.get("B1", 0)
            if q > 0 and not skip_b1:
                y = -bh/2.0 + cov + sd + md_b/2.0
                sets.append(RebarSetDef(y, q, str(win.bot_bar_type_selector.SelectedItem), md_b, ew_b, sx_b, "B1"))
            
            # T2
            q = cfg.get("T2", 0)
            if q > 0:
                gap = max(md_t, md_t2, 25.0/304.8)
                y = (bh/2.0 - cov - sd - md_t/2.0) - md_t/2.0 - gap - md_t2/2.0
                if not skip_t2:
                    sets.append(RebarSetDef(y, q, str(win.top_L2_type.SelectedItem if not win.chk_top_same.IsChecked else win.top_bar_type_selector.SelectedItem), md_t2, ew_t2, sx_t2, "T2"))
                if sp_t: spacers.append( (y + md_t2/2.0 + gap/2.0, sp_t, sp_s) )

            # B2
            q = cfg.get("B2", 0)
            if q > 0:
                gap = max(md_b, md_b2, 25.0/304.8)
                y = (-bh/2.0 + cov + sd + md_b/2.0) + md_b/2.0 + gap + md_b2/2.0
                if not skip_b2:
                    sets.append(RebarSetDef(y, q, str(win.bot_L2_type.SelectedItem if not win.chk_bot_same.IsChecked else win.bot_bar_type_selector.SelectedItem), md_b2, ew_b2, sx_b2, "B2"))
                if sp_t: spacers.append( (y - md_b2/2.0 - gap/2.0, sp_t, sp_s) )

            return sets, spacers
        def create_beam_batched(beams_list):
            with revit.Transaction("Batch Beam Rebar"):
                view = doc.ActiveView
                is_3d = isinstance(view, DB.View3D)
                
                for b_idx, b in enumerate(beams_list):
                    log("Processing Beam {}: ID {}".format(b_idx, b.Id))
                    dims = get_beam_dims_geometric(b)
                    bw, bh, cy, cz = dims
                    if not bw: continue
                    
                    # Supports
                    (s0, t0), (s1, t1) = get_supports_at_ends(b)
                    
                    # Geometry
                    c = b.Location.Curve
                    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
                    trans = b.GetTransform()
                    bx, bz = trans.BasisX, trans.BasisZ
                    by = trans.BasisY
                    
                    # Local Bounds
                    # Local Bounds from SOLID (Physical Face)
                    # p0/p1 from LocationCurve are usually Column Centers (Analytical).
                    # We need Physical Ends to avoid Hooks extending outside.
                    lx0, lx1 = 0.0, 0.0
                    try:
                        opt = DB.Options()
                        opt.ComputeReferences = True
                        opt.DetailLevel = DB.ViewDetailLevel.Fine
                        geom = b.get_Geometry(opt)
                        
                        def get_solids(g_elem):
                            sols = []
                            for g in g_elem:
                                if isinstance(g, DB.Solid) and g.Volume > 0: sols.append(g)
                                elif isinstance(g, DB.GeometryInstance): sols.extend(get_solids(g.GetInstanceGeometry()))
                            return sols
                        
                        solids = get_solids(geom)
                        if solids:
                            best_s = max(solids, key=lambda s: s.Volume)
                            # Project all vertices to Beam Axis (bx)
                            min_x, max_x = 99999.0, -99999.0
                            inv_t = trans.Inverse
                            for edge in best_s.Edges:
                                pts = edge.Tessellate()
                                for pt in pts:
                                    local_p = inv_t.OfPoint(pt)
                                    # local_p.X is along beam axis
                                    if local_p.X < min_x: min_x = local_p.X
                                    if local_p.X > max_x: max_x = local_p.X
                            
                            lx0, lx1 = min_x, max_x
                        else:
                             # Fallback to Curve
                             lx0, lx1 = (p0-trans.Origin).DotProduct(bx), (p1-trans.Origin).DotProduct(bx)

                    except: 
                        lx0, lx1 = (p0-trans.Origin).DotProduct(bx), (p1-trans.Origin).DotProduct(bx)

                    # Ensure order
                    if lx0 > lx1: lx0, lx1 = lx1, lx0
                    zs = (lx1-lx0)/3.0

                    def set_vis(r_elem):
                        if r_elem:
                            try:
                                r_elem.SetUnobscuredInView(view, True)
                                if is_3d: r_elem.SetSolidInView(view, True)
                            except: pass

                    # --- MAIN BARS (FULL SPAN + HOOKS) ---
                    # Logic: T1/B1 are continuous.
                    # Hooks: If Column -> Hook. If Beam -> Straight (No hook).
                    
                    # hk_start_top, hk_end_top = None, None # Removed as per instruction
                    # hk_start_bot, hk_end_bot = None, None # Removed as per instruction
                    
                    # if t0 == "Column": # Removed as per instruction
                    #     hk_start_top = hk_start # Removed as per instruction
                    #     hk_start_bot = hk_start # Removed as per instruction
                    # if t1 == "Column": # Removed as per instruction
                    #     hk_end_top = hk_end # Removed as per instruction
                    #     hk_end_bot = hk_end # Removed as per instruction

                    # Detect Main Bars (Use "End Sections" config as master for T1/B1)
                    # NOTE: If user wants different bars in Mid, this "Full Span" logic overrides it for T1/B1.
                    # This is a trade-off for "Continuity". 
                    # We assume T1/B1 are continuous.
                    
                    master_cfg = win.zone_configs["End Sections"]
                    mid_cfg = win.zone_configs["Middle Section"]
                    
                    # Check Continuity
                    # Only if Checkbox is Checked
                    use_cont = True
                    try: use_cont = win.chk_continuity.IsChecked
                    except: pass
                    
                    if use_cont:
                        t1_cont = (master_cfg["T1"] == mid_cfg["T1"] and master_cfg["T1"] > 0)
                        b1_cont = (master_cfg["B1"] == mid_cfg["B1"] and master_cfg["B1"] > 0)
                        t2_cont = (master_cfg["T2"] == mid_cfg["T2"] and master_cfg["T2"] > 0)
                        b2_cont = (master_cfg["B2"] == mid_cfg["B2"] and master_cfg["B2"] > 0)
                    else:
                        t1_cont = t2_cont = b1_cont = b2_cont = False

                    # Pre-calculate diameters for continuity blocks
                    md_t = top_bt_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                    md_t2 = find_t(win.top_L2_type.SelectedItem).get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble() if not win.chk_top_same.IsChecked else md_t
                    md_b = bot_bt_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                    md_b2 = find_t(win.bot_L2_type.SelectedItem).get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble() if not win.chk_bot_same.IsChecked else md_b

                    # Global Envelope Depth Calculation (Robust against voids/joins)
                    def get_col_depth(col, vec, origin):
                        depth = 0.5 # Default 150mm
                        debug_info = ["Col ID: " + str(col.Id)]
                        try:
                            # 1. Try Exact Geometry
                            opt = DB.Options()
                            opt.ComputeReferences = True
                            opt.DetailLevel = DB.ViewDetailLevel.Fine
                            geom = col.get_Geometry(opt)
                            
                            def get_sols(g_e):
                                sls = []
                                for g in g_e:
                                    if isinstance(g, DB.Solid) and g.Volume > 0: sls.append(g)
                                    elif isinstance(g, DB.GeometryInstance): sls.extend(get_sols(g.GetInstanceGeometry()))
                                return sls
                            
                            sols = get_sols(geom)
                            debug_info.append("Solids Found: " + str(len(sols)))
                            
                            inv_t = trans.Inverse
                            min_x, max_x = 99999.0, -99999.0
                            found = False
                            
                            if sols:
                                for s in sols:
                                    for edge in s.Edges:
                                        pts = edge.Tessellate()
                                        for pt in pts:
                                            local_p = inv_t.OfPoint(pt)
                                            if local_p.X < min_x: min_x = local_p.X
                                            if local_p.X > max_x: max_x = local_p.X
                                            found = True
                            
                            if found:
                                depth_geom = (max_x - min_x)
                                debug_info.append("Geom Depth: " + str(depth_geom))
                                # Use Geom Depth if reasonable (> 100mm)
                                if depth_geom > 0.3: 
                                    depth = depth_geom
                                    # log_to_file(debug_info)
                                    return depth
                                
                            # 2. Fallback to Bounding Box
                            debug_info.append("Falling back to BB")
                            bb = col.get_BoundingBox(None)
                            if bb:
                                debug_info.append("BB: " + str(bb.Min) + " to " + str(bb.Max))
                                # Project 8 corners of BB to Beam Axis
                                b_pts = [
                                    bb.Min,
                                    bb.Max,
                                    DB.XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z),
                                    DB.XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z),
                                    DB.XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
                                    DB.XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
                                    DB.XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
                                    DB.XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z)
                                ]
                                min_x, max_x = 99999.0, -99999.0
                                for pt in b_pts:
                                    local_p = inv_t.OfPoint(pt)
                                    if local_p.X < min_x: min_x = local_p.X
                                    if local_p.X > max_x: max_x = local_p.X
                                
                                depth = (max_x - min_x)
                                debug_info.append("BB Depth: " + str(depth))
                                
                                # Log ONLY if depth is small
                                if depth < 0.5: log_to_file("\n".join(debug_info))
                                return depth

                        except Exception as e: 
                            debug_info.append("Error: " + str(e))
                            log_to_file("\n".join(debug_info))
                            pass
                        
                        return depth

                    def get_anchorage_len(supp_el, is_start):
                        try:
                            # Use Cover from UI
                            b_cov = float(win.side_cover.Text) / 304.8
                            
                            if supp_el and supp_el.Category.Id.IntegerValue == COLUMN_CAT_ID:
                                # Direction into column
                                # If Start: -bx
                                # If End: bx
                                direction = -bx if is_start else bx
                                
                                # Origin
                                # If Start: Point at lx0.
                                # If End: Point at lx1.
                                x_base = lx0 if is_start else lx1
                                # Center Y/Z
                                pt_base = trans.OfPoint(DB.XYZ(x_base, cy, cz))
                                
                                depth = get_col_depth(supp_el, direction, pt_base)
                                
                                # Anchorage = Depth - Cover
                                # If Depth < Cover + min, fallback?
                                net_anch = depth - b_cov
                                return max(net_anch, 0.0 + (100.0/304.8)) # Ensure at least 100mm bond? 
                        except: pass
                        
                        return 150.0/304.8

                    # Draw Full Length T1 ONLY IF CONTINUOUS
                    if t1_cont:
                        # Top Y
                        sd = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                        yt1 = bh/2.0 - cov - sd - md_t/2.0
                        ew_t = bw - 2.0*cov - 2.0*sd - md_t
                        sx_t = -bw/2.0 + cov + sd + md_t/2.0
                        
                        qty = master_cfg["T1"]
                        # Offset/Spacing
                        offsets = []
                        if qty == 1: offsets = [0.0]
                        else:
                            sp = ew_t / (qty - 1)
                            offsets = [sx_t + i*sp for i in range(qty)]
                            
                        start_x = lx0 + off
                        hook_start_main = None
                        if t0 == "Column": 
                            anch = get_anchorage_len(s0, True)
                            start_x = lx0 - anch
                            hook_start_main = get_hook_90(doc) # Auto-apply 90 deg hook
                        
                        end_x = lx1 - off
                        hook_end_main = None
                        if t1 == "Column": 
                            anch = get_anchorage_len(s1, False)
                            end_x = lx1 + anch
                            hook_end_main = get_hook_90(doc) # Auto-apply 90 deg hook
                        
                        # p1 = DB.XYZ(start_x, 0, 0)
                        
                        for y_off in offsets:
                            p1_glb = trans.OfPoint(DB.XYZ(start_x, y_off+cy, yt1+cz))
                            p2_glb = trans.OfPoint(DB.XYZ(end_x, y_off+cy, yt1+cz))
                            l = DB.Line.CreateBound(p1_glb, p2_glb)
                            lc = List[DB.Curve]()
                            lc.Add(l)
                            try:
                                # TOP BARS -> Hook DOWN (Left inside Vertical Plane)
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, top_bt_t, hook_start_main, hook_end_main, b, by, lc, DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, True, True)
                                set_vis(r)
                            except: pass

                    if t2_cont:
                        # Top-L2 Y
                        sd = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                        gap = max(md_t, md_t2, 25.0/304.8)
                        yt2 = (bh/2.0 - cov - sd - md_t/2.0) - md_t/2.0 - gap - md_t2/2.0
                        ew_t2 = bw - 2.0*cov - 2.0*sd - md_t2
                        sx_t2 = -bw/2.0 + cov + sd + md_t2/2.0
                        
                        qty = master_cfg["T2"]
                        offsets = [0.0] if qty==1 else [sx_t2 + i*(ew_t2/(qty-1)) for i in range(qty)]
                        
                        start_x, end_x = lx0 + off, lx1 - off
                        h_s, h_e = None, None
                        if t0 == "Column": 
                            start_x = lx0 - get_anchorage_len(s0, True)
                            h_s = get_hook_90(doc)
                        if t1 == "Column": 
                            end_x = lx1 + get_anchorage_len(s1, False)
                            h_e = get_hook_90(doc)
                        
                        btinv = find_t(win.top_L2_type.SelectedItem if not win.chk_top_same.IsChecked else win.top_bar_type_selector.SelectedItem)
                        for y_off in offsets:
                            p1 = trans.OfPoint(DB.XYZ(start_x, y_off+cy, yt2+cz))
                            p2 = trans.OfPoint(DB.XYZ(end_x, y_off+cy, yt2+cz))
                            lc = List[DB.Curve]()
                            lc.Add(DB.Line.CreateBound(p1, p2))
                            try:
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, btinv, h_s, h_e, b, by, lc, DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, True, True)
                                set_vis(r)
                            except: pass

                    # Draw Full Length B1 ONLY IF CONTINUOUS
                    if b1_cont:
                        yb1 = -bh/2.0 + cov + sd + md_b/2.0
                        ew_b = bw - 2.0*cov - 2.0*sd - md_b
                        sx_b = -bw/2.0 + cov + sd + md_b/2.0
                        qty = master_cfg["B1"]
                        offsets = [0.0] if qty==1 else [sx_b + i*(ew_b/(qty-1)) for i in range(qty)]
                        
                        start_x = lx0 + off
                        hook_start_main = None
                        if t0 == "Column": 
                            anch = get_anchorage_len(s0, True)
                            start_x = lx0 - anch
                            hook_start_main = get_hook_90(doc) # Auto-apply 90 deg hook
                        
                        end_x = lx1 - off
                        hook_end_main = None
                        if t1 == "Column": 
                            anch = get_anchorage_len(s1, False)
                            end_x = lx1 + anch
                            hook_end_main = get_hook_90(doc) # Auto-apply 90 deg hook
                        
                        for y_off in offsets:
                            p1_glb = trans.OfPoint(DB.XYZ(start_x, y_off+cy, yb1+cz))
                            p2_glb = trans.OfPoint(DB.XYZ(end_x, y_off+cy, yb1+cz))
                            l = DB.Line.CreateBound(p1_glb, p2_glb)
                            lc = List[DB.Curve]()
                            lc.Add(l)
                            try:
                                # BOT BARS -> Hook UP (Right)
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, bot_bt_t, hook_start_main, hook_end_main, b, by, lc, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                                set_vis(r)
                            except: pass

                    if b2_cont:
                        # Bot-L2 Y
                        sd = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                        gap = max(md_b, md_b2, 25.0/304.8)
                        yb2 = (-bh/2.0 + cov + sd + md_b/2.0) + md_b/2.0 + gap + md_b2/2.0
                        ew_b2 = bw - 2.0*cov - 2.0*sd - md_b2
                        sx_b2 = -bw/2.0 + cov + sd + md_b2/2.0
                        
                        qty = master_cfg["B2"]
                        offsets = [0.0] if qty==1 else [sx_b2 + i*(ew_b2/(qty-1)) for i in range(qty)]
                        
                        start_x, end_x = lx0 + off, lx1 - off
                        h_s, h_e = None, None
                        if t0 == "Column": 
                            start_x = lx0 - get_anchorage_len(s0, True)
                            h_s = get_hook_90(doc)
                        if t1 == "Column": 
                            end_x = lx1 + get_anchorage_len(s1, False)
                            h_e = get_hook_90(doc)
                        
                        btinv = find_t(win.bot_L2_type.SelectedItem if not win.chk_bot_same.IsChecked else win.bot_bar_type_selector.SelectedItem)
                        for y_off in offsets:
                            p1 = trans.OfPoint(DB.XYZ(start_x, y_off+cy, yb2+cz))
                            p2 = trans.OfPoint(DB.XYZ(end_x, y_off+cy, yb2+cz))
                            lc = List[DB.Curve]()
                            lc.Add(DB.Line.CreateBound(p1, p2))
                            try:
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, btinv, h_s, h_e, b, by, lc, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                                set_vis(r)
                            except: pass


                    # --- STIRRUPS & EXTRA LAYERS ---
                    def mks(sx, ex, sp):
                        lw, lh = bw-2*cov, bh-2*cov
                        raw_pts = [DB.XYZ(sx, cy-lw/2, cz-lh/2), 
                                   DB.XYZ(sx, cy+lw/2, cz-lh/2), 
                                   DB.XYZ(sx, cy+lw/2, cz+lh/2), 
                                   DB.XYZ(sx, cy-lw/2, cz+lh/2)]
                        pts = [raw_pts[2], raw_pts[1], raw_pts[0], raw_pts[3]] # TR, CW
                        
                        curv = List[DB.Curve]()
                        try:
                            for i in range(4): 
                                p_start = trans.OfPoint(pts[i])
                                p_end = trans.OfPoint(pts[(i+1)%4])
                                curv.Add(DB.Line.CreateBound(p_start, p_end))
                            
                            r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.StirrupTie, st_t, hook_t, hook_t, b, bx, curv, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                            if r:
                                zl = ex-sx
                                qty = int(math.floor(zl/sp)) + 1
                                if qty > 1: r.GetShapeDrivenAccessor().SetLayoutAsNumberWithSpacing(qty, sp, True, True, True)
                                set_vis(r)
                        except Exception as e: log("Stirrup Err: " + str(e))

                    physical_zones = [
                        {"name": "End Sections",   "sx": lx0+off,   "ex": lx0+zs,   "idx": 0},
                        {"name": "Middle Section", "sx": lx0+zs,    "ex": lx0+2*zs, "idx": 1},
                        {"name": "End Sections",   "sx": lx0+2*zs,  "ex": lx1-off,  "idx": 2}
                    ]
                    
                    mks(lx0+off, lx0+zs, es)
                    mks(lx0+zs, lx0+2*zs, ms)
                    mks(lx0+2*zs, lx1-off, es)
                    

                    for pz in physical_zones:
                        z_name = pz["name"]
                        sx, ex, idx = pz["sx"], pz["ex"], pz["idx"]
                        if ex <= sx: continue 
                        
                        try:
                            # Pass flags to Skip layers if they are continuous
                            sets, spacers = get_rebar_sets(z_name, bw, bh, skip_t1=t1_cont, skip_b1=b1_cont, skip_t2=t2_cont, skip_b2=b2_cont)
                        except Exception as e: 
                            log("GetSets Err: " + str(e))
                            sets, spacers = [], []
                        
                        for rb_set in sets:
                            # Add Hooks if Zoned T1/B1 (start/end)
                            h_s, h_e = None, None
                            tag = getattr(rb_set, "layer_tag", "")
                            
                            # Hooks only at very ends of beam
                            if tag in ["T1", "T2"]:
                                if idx == 0 and t0 == "Column": h_s = get_hook_90(doc)
                                if idx == 2 and t1 == "Column": h_e = get_hook_90(doc)
                            if tag in ["B1", "B2"]:
                                if idx == 0 and t0 == "Column": h_s = get_hook_90(doc)
                                if idx == 2 and t1 == "Column": h_e = get_hook_90(doc)
                                
                            start_loc, end_loc = sx, ex
                            

                            # Anchorage extension if hooked at ends
                            if h_s: start_loc -= get_anchorage_len(s0, True)
                            if h_e: end_loc += get_anchorage_len(s1, False)

                            qty = rb_set.qty
                            if qty < 1: continue
                            offs = [0.0]
                            if qty > 1:
                                sp_b = rb_set.array_len / (qty - 1)
                                offs = [rb_set.start_x_local + i*sp_b for i in range(qty)]
                            
                            for x_off in offs:
                                p1 = trans.OfPoint(DB.XYZ(start_loc, x_off+cy, rb_set.y_local+cz))
                                p2 = trans.OfPoint(DB.XYZ(end_loc, x_off+cy, rb_set.y_local+cz))
                                l = DB.Line.CreateBound(p1, p2)
                                lc = List[DB.Curve]()
                                lc.Add(l)
                                try:
                                    orient = DB.Structure.RebarHookOrientation.Right
                                    if tag in ["T1", "T2"]: orient = DB.Structure.RebarHookOrientation.Left
                                    elif tag in ["B1", "B2"]: orient = DB.Structure.RebarHookOrientation.Right
                                    
                                    this_bt_t = find_t(rb_set.type_name) or top_bt_t
                                    r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, this_bt_t, h_s, h_e, b, by, lc, orient, orient, True, True)
                                    set_vis(r)
                                except: pass
                        
                        # Spacers (Side Bars or Layer Separators)
                        for (spy, sp_type, sp_spacing) in spacers:
                            try:
                                sd = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                                spl = bw - 2*cov - 2*sd
                                if spl > 0:
                                    c_pts = [DB.XYZ(sx, -spl/2 + cy, spy + cz), DB.XYZ(sx, spl/2 + cy, spy + cz)]
                                    lc = List[DB.Curve]()
                                    lc.Add(DB.Line.CreateBound(trans.OfPoint(c_pts[0]), trans.OfPoint(c_pts[1])))
                                    r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, sp_type, None, None, b, bx, lc, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                                    if r:
                                        zl = ex-sx
                                        qty = int(math.floor(zl/sp_spacing))
                                        if qty > 1: r.GetShapeDrivenAccessor().SetLayoutAsNumberWithSpacing(qty, sp_spacing, True, True, True)
                                        set_vis(r)
                            except: pass

                    # Side Bars
                    if side_t and side_q > 0:
                        try:
                             # Side Logic
                             # Inner Height
                             st_d = st_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                             s_inner_h = bh - 2*cov - 2*st_d
                             q_per_side = side_q / 2.0
                             if s_inner_h > 0 and q_per_side > 0:
                                 step = s_inner_h / (q_per_side + 1)
                                 y_start = -s_inner_h/2.0 + step
                                 
                                 # X Offset
                                 sid_d = side_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                                 x_off = bw/2.0 - cov - st_d - sid_d/2.0
                                 
                                 for i in range(int(q_per_side)):
                                     y_loc = y_start + i*step
                                     for x_side in [-x_off, x_off]:
                                         p1 = DB.XYZ(lx0+off, x_side+cy, y_loc+cz)
                                         p2 = DB.XYZ(lx1-off, x_side+cy, y_loc+cz)
                                         lc = List[DB.Curve]()
                                         lc.Add(DB.Line.CreateBound(trans.OfPoint(p1), trans.OfPoint(p2)))
                                         r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, side_t, None, None, b, bz, lc, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                                         set_vis(r)
                        except Exception as ex: log("SideBar Err: " + str(ex))
                
                if debug_log: forms.alert("Log:\n" + "\n".join(debug_log))
                else: forms.alert("Beam Rebar Complete!")

        # ----------------------
        # COLUMN LOGIC
        # ----------------------
        def create_column_batched(cols):
            try:
                cw = float(win.col_width_ui.Text) / 304.8
                cd = float(win.col_depth_ui.Text) / 304.8
                ccov = float(win.col_cover.Text) / 304.8
                tie_s_end = float(win.col_tie_spacing_end.Text) / 304.8
                tie_s_mid = float(win.col_tie_spacing_mid.Text) / 304.8
            except: 
                log("Invalid Column Inputs")
                forms.alert("Log:\n" + "\n".join(debug_log))
                return

            tie_t = find_t(str(win.col_tie_type.SelectedItem))
            # Tie Hook Logic (Auto 135)
            # hooks = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarHookType).ToElements() # Removed as per instruction
            # hook_t = next((h for h in hooks if "135" in (h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or h.Name)), None) # Removed as per instruction
            # if not hook_t: hook_t = next((h for h in hooks if "90" in (h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or h.Name)), None) # Removed as per instruction
            
            corn_t = find_t(str(win.col_corner_type.SelectedItem))
            sidex_t = find_t(str(win.col_side_x_type.SelectedItem))
            sidey_t = find_t(str(win.col_side_y_type.SelectedItem))
            
            try: qx = int(str(win.col_side_x_qty.SelectedItem))
            except: qx = 0
            try: qy = int(str(win.col_side_y_qty.SelectedItem))
            except: qy = 0

            if not tie_t or not corn_t: return forms.alert("Missing Bar Types")
            tie_d = tie_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()

            with revit.Transaction("Batch Column Rebar"):
                view = doc.ActiveView
                is_3d = isinstance(view, DB.View3D)
                def set_vis(r_elem):
                    if r_elem:
                        try:
                            r_elem.SetUnobscuredInView(view, True)
                            if is_3d: r_elem.SetSolidInView(view, True)
                        except: pass

                for col in cols:
                    log("Processing Column: {}".format(col.Id))
                    bb = col.get_BoundingBox(None)
                    if not bb: continue
                    
                    trans = col.GetTransform()
                    org = trans.Origin
                    h = bb.Max.Z - bb.Min.Z
                    z_min = bb.Min.Z
                    z_max = bb.Max.Z
                    
                    bx, by, bz = trans.BasisX, trans.BasisY, trans.BasisZ
                    
                    # 1. TIES (CONFINEMENT ZONES)
                    dx = cw/2 - ccov - tie_d/2
                    dy = cd/2 - ccov - tie_d/2
                    
                    def get_global(x_loc, y_loc):
                        # Transform local x,y to global coordinates including rotation
                        return org + bx * x_loc + by * y_loc

                    # Tie Shape Loop
                    # TR(3) -> BR(2) -> BL(1) -> TL(0) -> TR(3)
                    # We store just the (x,y) pairs first
                    coords_local = [
                        (-dx, dy),  # TL
                        (-dx, -dy), # BL
                        (dx, -dy),  # BR
                        (dx, dy)    # TR
                    ]
                    
                    # Convert to Global XY objects (Z will be added later)
                    pts_global_base = [get_global(x, y) for x, y in coords_local]
                    
                    # Re-create loop for each placement? No, CreateFromCurves takes loop and layout.
                    # But we need 3 sets for 3 zones.
                    # Curve Loop is constant shape (except for z).
                    # Actually standard CreateFromCurves makes a single Rebar Element.
                    # We can set layout rules. But standard API only supports Uniform, or NumberWithSpacing.
                    # It does NOT support complex variable spacing in one element easily (unless custom).
                    # Easier to create 3 separate Rebar elements for 3 zones.
                    
                    # --- ANCHORAGE DETECTION ---
                    def get_foundation(col_elem):
                        bb = col_elem.get_BoundingBox(None)
                        if not bb: return None
                        pt_check = (bb.Min + bb.Max)/2.0
                        pt_check = DB.XYZ(pt_check.X, pt_check.Y, bb.Min.Z - 0.5)
                        d = 1.0 
                        outline = DB.Outline(pt_check - DB.XYZ(d,d,d), pt_check + DB.XYZ(d,d,d))
                        filt = DB.BoundingBoxIntersectsFilter(outline)
                        foundations = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFoundation).WherePasses(filt).ToElements()
                        if foundations: return foundations[0]
                        return None

                    foundation = get_foundation(col)
                    anch_depth = 0.0
                    hook_bot = None
                    if win.chk_col_anchorage.IsChecked and foundation:
                        f_bb = foundation.get_BoundingBox(None)
                        if f_bb:
                            f_cov = ccov
                            embed = (z_min - f_bb.Min.Z) - f_cov
                            if embed > 0:
                                anch_depth = embed
                                hooks_els = DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarHookType).ToElements()
                                h90 = next((h for h in hooks_els if "90" in (h.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or h.Name)), None)
                                hook_bot = h90
                                log("Anchoring to Foundation: " + str(embed*304.8) + "mm")

                    # Define Zones
                    try: h_conf = float(win.col_conf_height.Text)/304.8
                    except: h_conf = h/6.0
                    
                    try: s_end = float(win.col_tie_spacing_end.Text)/304.8
                    except: s_end = 100/304.8
                    
                    try: s_mid = float(win.col_tie_spacing_mid.Text)/304.8
                    except: s_mid = 200/304.8

                    # Extend first zone into foundation if anchored
                    z_start_tie = z_min + ccov
                    if anch_depth > 0:
                        z_start_tie = z_min - anch_depth + ccov

                    zones = [
                        (z_start_tie, z_min + h_conf, s_end),
                        (z_min + h_conf, z_max - h_conf, s_mid),
                        (z_max - h_conf, z_max - ccov, s_end)
                    ]
                    
                    for (z0, z1, sp) in zones:
                         if z1 <= z0: continue
                         
                         # Shape at z0
                         c_loop = List[DB.Curve]()
                         
                         # Points at z0
                         def pz(p_base, z_val): return DB.XYZ(p_base.X, p_base.Y, z_val)
                         
                         p0 = pz(pts_global_base[0], z0)
                         p1 = pz(pts_global_base[1], z0)
                         p2 = pz(pts_global_base[2], z0)
                         p3 = pz(pts_global_base[3], z0)
                         
                         c_loop.Add(DB.Line.CreateBound(p3, p2)) # TR->BR
                         c_loop.Add(DB.Line.CreateBound(p2, p1)) # BR->BL
                         c_loop.Add(DB.Line.CreateBound(p1, p0)) # BL->TL
                         c_loop.Add(DB.Line.CreateBound(p0, p3)) # TL->TR
                         
                         try:
                             r_tie = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.StirrupTie, tie_t, hook_t, hook_t, col, bz, c_loop, DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right, True, True)
                             if r_tie:
                                 len_z = z1 - z0
                                 qty = int(len_z / sp) + 1
                                 if qty > 1: r_tie.GetShapeDrivenAccessor().SetLayoutAsNumberWithSpacing(qty, sp, True, True, True)
                                 set_vis(r_tie)
                         except Exception as e: log("Tie Zone Err: " + str(e))

                    # 2. VERTICALS
                    v_len = h - 2*ccov
                    if v_len <= 0: continue
                    
                    try: ext_len = float(win.col_top_extension.Text)/304.8
                    except: ext_len = 0.0
                    
                    c_bar_d = corn_t.get_Parameter(DB.BuiltInParameter.REBAR_BAR_DIAMETER).AsDouble()
                    off_cx = cw/2 - ccov - tie_d - c_bar_d/2
                    off_cy = cd/2 - ccov - tie_d - c_bar_d/2
                    
                    corners = [(-off_cx,-off_cy), (off_cx,-off_cy), (off_cx,off_cy), (-off_cx,off_cy)]
                    
                    for (cx_loc, cy_loc) in corners:
                        p_bot = org + bx*cx_loc + by*cy_loc
                        p_bot = DB.XYZ(p_bot.X, p_bot.Y, z_min + ccov - anch_depth)
                        p_top = DB.XYZ(p_bot.X, p_bot.Y, z_max - ccov + ext_len)
                        lc = List[DB.Curve]()
                        lc.Add(DB.Line.CreateBound(p_bot, p_top))
                        try:
                            # OUTWARD ORIENTATION:
                            # Normal of the rebar should be perpendicular to the desired hook direction.
                            # Desired Hook direction = Vector from center (cx_loc, cy_loc)
                            # For Vertical Bar (Z+), Normal = BarDir (Z) x HookDir
                            hook_dir_local = DB.XYZ(cx_loc, cy_loc, 0).Normalize()
                            bar_dir = DB.XYZ.BasisZ
                            normal_local = bar_dir.CrossProduct(hook_dir_local)
                            normal_glb = bx * normal_local.X + by * normal_local.Y
                            
                            # Using 'Left' orientation with this cross-product normal will point the hook 'Out' (HookDir)
                            rv = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, corn_t, hook_bot, None, col, normal_glb, lc, DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, True, True)
                            set_vis(rv)
                        except: pass
                    
                    # Side X
                    if qx > 0 and sidex_t:
                        step_x = (2*off_cx) / (qx + 1)
                        for i in range(1, qx+1):
                            x_pos = -off_cx + i*step_x
                            for y_mul in [-1, 1]:
                                p_bot = org + bx*x_pos + by*(off_cy*y_mul)
                                p_bot = DB.XYZ(p_bot.X, p_bot.Y, z_min + ccov - anch_depth)
                                p_top = DB.XYZ(p_bot.X, p_bot.Y, z_max - ccov + ext_len)
                                lc = List[DB.Curve]()
                                lc.Add(DB.Line.CreateBound(p_bot, p_top))
                                try:
                                    # Point Outward (along Y axis)
                                    h_dir = DB.XYZ(0, y_mul, 0)
                                    n_local = DB.XYZ.BasisZ.CrossProduct(h_dir)
                                    n_glb = bx * n_local.X + by * n_local.Y
                                    rv = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, sidex_t, hook_bot, None, col, n_glb, lc, DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, True, True)
                                    set_vis(rv)
                                except: pass
                    
                    # Side Y
                    if qy > 0 and sidey_t:
                        step_y = (2*off_cy) / (qy + 1)
                        for i in range(1, qy+1):
                            y_pos = -off_cy + i*step_y
                            for x_mul in [-1, 1]:
                                p_bot = org + bx*(off_cx*x_mul) + by*y_pos
                                p_bot = DB.XYZ(p_bot.X, p_bot.Y, z_min + ccov - anch_depth)
                                p_top = DB.XYZ(p_bot.X, p_bot.Y, z_max - ccov + ext_len)
                                lc = List[DB.Curve]()
                                lc.Add(DB.Line.CreateBound(p_bot, p_top))
                                try:
                                    # Point Outward (along X axis)
                                    h_dir = DB.XYZ(x_mul, 0, 0)
                                    n_local = DB.XYZ.BasisZ.CrossProduct(h_dir)
                                    n_glb = bx * n_local.X + by * n_local.Y
                                    rv = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, sidey_t, hook_bot, None, col, n_glb, lc, DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, True, True)
                                    set_vis(rv)
                                except: pass
                
                if debug_log: forms.alert("Log:\n" + "\n".join(debug_log))
                else: forms.alert("Column Rebar Created!")

        def create_footing_batched(footings):
            with revit.Transaction("Batch Footing Rebar"):
                view = doc.ActiveView
                is_3d = isinstance(view, DB.View3D)
                
                def set_vis(r_elem):
                    if r_elem:
                        try:
                            r_elem.SetUnobscuredInView(view, True)
                            if is_3d: r_elem.SetSolidInView(view, True)
                        except: pass

                for f in footings:
                    try:
                        # 1. Dimensions (Solid-based for rotated footings)
                        trans = f.GetTransform()
                        inv = trans.Inverse
                        opt = DB.Options()
                        opt.DetailLevel = DB.ViewDetailLevel.Fine
                        geom = f.get_Geometry(opt)
                        
                        solids = []
                        def get_sols(g_e):
                            for g in g_e:
                                if isinstance(g, DB.Solid) and g.Volume > 0: solids.append(g)
                                elif isinstance(g, DB.GeometryInstance): get_sols(g.GetInstanceGeometry())
                        get_sols(geom)
                        if not solids: continue
                        best_s = max(solids, key=lambda s: s.Volume)
                        
                        # Local Bounding Box
                        l_min_x, l_max_x = 9999.0, -9999.0
                        l_min_y, l_max_y = 9999.0, -9999.0
                        l_min_z, l_max_z = 9999.0, -9999.0
                        
                        for edge in best_s.Edges:
                            for pt in edge.Tessellate():
                                lp = inv.OfPoint(pt)
                                l_min_x, l_max_x = min(l_min_x, lp.X), max(l_max_x, lp.X)
                                l_min_y, l_max_y = min(l_min_y, lp.Y), max(l_max_y, lp.Y)
                                l_min_z, l_max_z = min(l_min_z, lp.Z), max(l_max_z, lp.Z)
                        
                        fw = abs(l_max_x - l_min_x)
                        fl = abs(l_max_y - l_min_y)
                        fh = abs(l_max_z - l_min_z)
                        
                        fcov = float(win.footing_cover.Text)/304.8
                        h90 = get_hook_90(doc)
                        
                        def create_mat(is_top):
                            z_off = (l_max_z - fcov) if is_top else (l_min_z + fcov)
                            
                            # X-Bars (Curves along Local X, array along Local Y)
                            xt_n = str(win.footing_tx_type.SelectedItem if is_top else win.footing_bx_type.SelectedItem)
                            xs_v = float(win.footing_tx_spacing.Text if is_top else win.footing_bx_spacing.Text)/304.8
                            xt = find_t(xt_n)
                            
                            if xt:
                                p_start_l = DB.XYZ(l_min_x + fcov, l_min_y + fcov, z_off)
                                p_end_l = DB.XYZ(l_max_x - fcov, l_min_y + fcov, z_off)
                                c = DB.Line.CreateBound(trans.OfPoint(p_start_l), trans.OfPoint(p_end_l))
                                
                                # Normal: Array INTO footing (+Y)
                                norm = trans.BasisY
                                # Hook: X x Y = Z+ (Up). For Bottom use Right (Up), for Top use Left (Down).
                                ho = DB.Structure.RebarHookOrientation.Right if not is_top else DB.Structure.RebarHookOrientation.Left
                                
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, xt, h90, h90, f, norm, [c], ho, ho, True, True)
                                if r:
                                    qty = int((fl - 2.0*fcov) / xs_v) + 1
                                    r.GetShapeDrivenAccessor().SetLayoutAsNumberWithSpacing(qty, xs_v, True, True, True)
                                    set_vis(r)
                                    
                            # Y-Bars (Curves along Local Y, array along Local X)
                            yt_n = str(win.footing_ty_type.SelectedItem if is_top else win.footing_by_type.SelectedItem)
                            ys_v = float(win.footing_ty_spacing.Text if is_top else win.footing_by_spacing.Text)/304.8
                            yt = find_t(yt_n)
                            
                            if yt:
                                p_start_l = DB.XYZ(l_min_x + fcov, l_min_y + fcov, z_off)
                                p_end_l = DB.XYZ(l_min_x + fcov, l_max_y - fcov, z_off)
                                c = DB.Line.CreateBound(trans.OfPoint(p_start_l), trans.OfPoint(p_end_l))
                                
                                # Normal: Array INTO footing (+X)
                                norm = trans.BasisX
                                # Hook: Y x X = Z- (Down). For Bottom use Left (Up), for Top use Right (Down).
                                ho = DB.Structure.RebarHookOrientation.Left if not is_top else DB.Structure.RebarHookOrientation.Right
                                
                                r = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, yt, h90, h90, f, norm, [c], ho, ho, True, True)
                                if r:
                                    qty = int((fw - 2.0*fcov) / ys_v) + 1
                                    r.GetShapeDrivenAccessor().SetLayoutAsNumberWithSpacing(qty, ys_v, True, True, True)
                                    set_vis(r)

                        create_mat(False) # Bottom
                        if win.chk_footing_top_mat.IsChecked: create_mat(True) # Top
                        
                    except Exception as e: log("Footing Err: " + str(e))
                
                forms.alert("Footing Rebar Created!")

        # ----------------------
        # DISPATCHER
        # ----------------------
        if win.selected_tab_index == 0:
            # BEAM Selected
            sel_beams = [e for e in beams if e.Category.Id.IntegerValue == FRAMING_CAT_ID]
            if not sel_beams: forms.alert("No Beams Selected!")
            else: create_beam_batched(sel_beams)
        elif win.selected_tab_index == 1:
            # COLUMN Selected
            sel_cols = [e for e in beams if e.Category.Id.IntegerValue == COLUMN_CAT_ID]
            if not sel_cols: forms.alert("No Columns Selected!")
            else: create_column_batched(sel_cols)
        elif win.selected_tab_index == 2:
            # FOOTING Selected
            sel_footings = [e for e in beams if e.Category.Id.IntegerValue == FOOTING_CAT_ID]
            if not sel_footings: forms.alert("No Footings Selected!")
            else: create_footing_batched(sel_footings)

    except Exception: forms.alert(traceback.format_exc())
    finally:
        try:
            if 'temp' in locals() and os.path.exists(temp): os.remove(temp)
        except: pass

if __name__ == '__main__': create_rebar()
