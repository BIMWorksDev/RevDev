#! ironpython
# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List
from Autodesk.Revit.UI.Selection import ObjectType

doc = revit.doc
uidoc = revit.uidoc

class CategoryWrapper(forms.TemplateListItem):
    @property
    def name(self):
        return self.item.Name

def copy_by_category():
    # 1. Collect all Link Instances
    collector = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
    links = list(collector)
    
    if not links:
        forms.alert("No linked models found in the current project.", exitscript=True)
    
    # Map Name -> LinkInstance
    link_dict = {}
    for link in links:
        link_doc = link.GetLinkDocument()
        if link_doc:
            name = "{} (ID: {})".format(link.Name, link.Id)
            link_dict[name] = link
    
    if not link_dict:
        forms.alert("No LOADED links found.", exitscript=True)
        
    sorted_names = sorted(link_dict.keys())

    # 2. Select Link
    selected_name = forms.SelectFromList.show(
        sorted_names,
        title="Select Source Link",
        multiselect=False
    )
    
    if not selected_name:
        return
        
    selected_link_instance = link_dict[selected_name]
    source_doc = selected_link_instance.GetLinkDocument()
    transform = selected_link_instance.GetTotalTransform()
    
    # 3. Collect all elements in that link to find categories
    all_elements = DB.FilteredElementCollector(source_doc).WhereElementIsNotElementType().ToElements()
    
    category_map = {}
    for el in all_elements:
        if el.Category:
            cat_id = el.Category.Id.IntegerValue
            if cat_id not in category_map:
                category_map[cat_id] = el.Category

    # 4. Select Categories
    sorted_categories = sorted(category_map.values(), key=lambda c: c.Name)
    selected_categories = forms.SelectFromList.show(
        [CategoryWrapper(c) for c in sorted_categories],
        title="Select Categories to Copy from Link",
        multiselect=True,
        button_name="Select Categories"
    )

    if not selected_categories:
        return

    selected_cat_ids = [c.Id for c in selected_categories]

    # 5. Collect Elements of Selected Categories
    cat_filter = DB.ElementMulticategoryFilter(List[DB.ElementId](selected_cat_ids))
    elements_to_copy = DB.FilteredElementCollector(source_doc).WherePasses(cat_filter).WhereElementIsNotElementType().ToElementIds()

    if not elements_to_copy:
        forms.alert("No elements found in selected categories.", exitscript=True)

    # 6. Copy Elements
    t = DB.Transaction(doc, "Copy Linked Elements by Category")
    t.Start()
    
    try:
        options = DB.CopyPasteOptions()
        copied_ids = DB.ElementTransformUtils.CopyElements(
            source_doc,
            elements_to_copy,
            doc,
            transform, 
            options
        )
        
        print("Successfully copied {} elements from link.".format(len(copied_ids)))
        t.Commit()
    except Exception as e:
        print("Error during copy: {}".format(e))
        t.RollBack()

def copy_by_picking():
    try:
        # Prompt user to select elements from links
        refs = uidoc.Selection.PickObjects(ObjectType.LinkedElement, "Select elements from linked models to copy")
    except Exception:
        # Check if it was a cancellation
        return

    if not refs:
        return

    # Group valid selections by Link Instance
    # Key: Link Instance ElementId, Value: List of ElementIds to copy from that link
    link_map = {}

    for ref in refs:
        link_instance_id = ref.ElementId
        linked_element_id = ref.LinkedElementId
        
        if link_instance_id not in link_map:
            link_map[link_instance_id] = []
        link_map[link_instance_id].append(linked_element_id)

    if not link_map:
        return

    t = DB.Transaction(doc, "Copy Picked Linked Elements")
    t.Start()
    
    total_copied = 0
    error_count = 0
    
    try:
        for link_inst_id, elem_ids in link_map.items():
            link_inst = doc.GetElement(link_inst_id)
            if not isinstance(link_inst, DB.RevitLinkInstance):
                continue
                
            link_doc = link_inst.GetLinkDocument()
            if not link_doc:
                print("Could not retrieve document for link instance ID: {}".format(link_inst_id))
                continue
                
            transform = link_inst.GetTotalTransform()
            options = DB.CopyPasteOptions()
            
            # Prepare IDs list
            ids_collection = List[DB.ElementId](elem_ids)
            
            copied = DB.ElementTransformUtils.CopyElements(
                link_doc,
                ids_collection,
                doc,
                transform,
                options
            )
            total_copied += len(copied)
            
        print("Successfully copied {} elements.".format(total_copied))
        t.Commit()
        
    except Exception as e:
        print("Error during copy transaction: {}".format(e))
        t.RollBack()

def main():
    options = ["Pick Elements from Link", "Select Categories from Link"]
    res = forms.CommandSwitchWindow.show(
        options,
        message="Select Copy Method:"
    )
    
    if res == options[0]:
        copy_by_picking()
    elif res == options[1]:
        copy_by_category()
    else:
        # Cancelled or closed
        pass

if __name__ == '__main__':
    main()
