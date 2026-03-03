#! ironpython
# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc = revit.doc
uidoc = revit.uidoc

class CategoryWrapper(forms.TemplateListItem):
    @property
    def name(self):
        return self.item.Name

def get_level_param(element):
    # Try different parameter sources for "Level"
    p = element.get_Parameter(DB.BuiltInParameter.FAMILY_LEVEL_PARAM)
    if p and not p.IsReadOnly: return p
    p = element.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
    if p and not p.IsReadOnly: return p
    p = element.get_Parameter(DB.BuiltInParameter.SCHEDULE_BASE_LEVEL_PARAM)
    if p and not p.IsReadOnly: return p
    for name in ["Level", "Base Level", "Base Constraint"]:
        p = element.LookupParameter(name)
        if p and not p.IsReadOnly: return p
    return None

def get_offset_param(element):
    p = element.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET)
    if p and not p.IsReadOnly: return p
    p = element.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
    if p and not p.IsReadOnly: return p
    p = element.get_Parameter(DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
    if p and not p.IsReadOnly: return p
    names = ["Base Offset", "Offset", "Height Offset From Level", "Offset from Host"]
    for name in names:
        p = element.LookupParameter(name)
        if p and not p.IsReadOnly: return p
    return None

def main():
    # 1. Get All Levels
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())
    levels.sort(key=lambda l: l.Elevation)
    level_dict = {l.Name: l for l in levels}
    sorted_level_names = sorted(level_dict.keys(), key=lambda n: level_dict[n].Elevation)

    # 2. Select Source Level
    source_level_name = forms.SelectFromList.show(
        sorted_level_names,
        title="Select Source Level",
        multiselect=False
    )
    if not source_level_name:
        script.exit()
    
    source_level = level_dict[source_level_name]
    source_level_id = source_level.Id

    # 3. Find All Categories on that Level
    all_elements = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
    hosted_elements = []
    category_map = {}
    
    for el in all_elements:
        on_level = False
        if el.LevelId == source_level_id:
            on_level = True
        else:
            p_level = get_level_param(el)
            if p_level and p_level.StorageType == DB.StorageType.ElementId:
                if p_level.AsElementId() == source_level_id:
                    on_level = True
        
        if on_level:
            hosted_elements.append(el)
            if el.Category:
                cat_id = el.Category.Id.IntegerValue
                if cat_id not in category_map:
                    category_map[cat_id] = el.Category

    if not hosted_elements:
        forms.alert("No elements found on level: {}".format(source_level_name), exitscript=True)

    # 4. Select Categories
    sorted_categories = sorted(category_map.values(), key=lambda c: c.Name)
    selected_categories = forms.SelectFromList.show(
        [CategoryWrapper(c) for c in sorted_categories],
        title="Select Categories to Transfer",
        multiselect=True,
        button_name="Select Categories"
    )
    
    if not selected_categories:
        script.exit()

    selected_cat_ids = [c.Id for c in selected_categories]
    final_elements = [el for el in hosted_elements if el.Category and el.Category.Id in selected_cat_ids]

    # 5. Select Target Level
    target_level_name = forms.SelectFromList.show(
        sorted_level_names,
        title="Select Target Level",
        multiselect=False
    )
    if not target_level_name:
        script.exit()
        
    target_level = level_dict[target_level_name]
    target_level_id = target_level.Id
    target_elevation = target_level.Elevation

    # 6. Transaction
    with revit.Transaction("Change Element Level (Keep Position)"):
        success_count = 0
        for el in final_elements:
            try:
                p_level = get_level_param(el)
                if not p_level: continue
                    
                current_level_id = el.LevelId
                if current_level_id == DB.ElementId.InvalidElementId:
                    if p_level.StorageType == DB.StorageType.ElementId:
                        current_level_id = p_level.AsElementId()
                
                if current_level_id == DB.ElementId.InvalidElementId: continue
                    
                current_level_el = doc.GetElement(current_level_id)
                if not current_level_el: continue

                p_offset = get_offset_param(el)
                current_offset_val = p_offset.AsDouble() if p_offset else 0.0
                
                absolute_z = current_level_el.Elevation + current_offset_val
                new_offset_val = absolute_z - target_elevation
                
                p_level.Set(target_level_id)
                if p_offset:
                    p_offset.Set(new_offset_val)
                
                success_count += 1
            except Exception as e:
                print("Error on element {}: {}".format(el.Id, e))

    print("Successfully transferred {} elements to Level: {}".format(success_count, target_level_name))

if __name__ == '__main__':
    main()
