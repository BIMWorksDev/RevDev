#! ironpython
# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc

# Logger for output
output = script.get_output()

def get_elements_by_selection():
    selection = uidoc.Selection.GetElementIds()
    if not selection:
        forms.alert("No elements selected.", exitscript=True)
    return [doc.GetElement(id) for id in selection]

def get_elements_by_family_type():
    # Collect all Family Symbols (Types)
    # Optimization: Filter only used types or just all types? All types is safer.
    collector = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
    
    # Create a dictionary for the form {DisplayName: Element}
    # We want to show "FamilyName : TypeName" to be clear
    types_dict = {}
    for fs in collector:
        try:
            # Safer name retrieval
            fam_name = fs.FamilyName if hasattr(fs, "FamilyName") else fs.Family.Name
            # fs.Name sometimes fails in IronPython for specific symbols, use Parameter instead
            p_name = fs.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
            type_name = p_name.AsString() if p_name else fs.Name 
            
            name = "{} : {}".format(fam_name, type_name)
            types_dict[name] = fs
        except Exception:
            continue

    if not types_dict:
        forms.alert("No Family Types found in project.", exitscript=True)

    # Sort keys
    sorted_names = sorted(types_dict.keys())

    # Ask user to pick
    selected_name = forms.SelectFromList.show(
        sorted_names,
        title="Select Family Type",
        multiselect=False
    )

    if not selected_name:
        script.exit()

    selected_symbol = types_dict[selected_name]

    # Find all instances of this symbol
    # Note: FamilyInstance filter might miss some things if they aren't strictly FamilyInstances (e.g. System Families), 
    # but FamilySymbol implies loadable families.
    instance_collector = DB.FilteredElementCollector(doc)\
        .WhereElementIsNotElementType()\
        .OfClass(DB.FamilyInstance)\
        .OfSymbol(selected_symbol.Id) # OfSymbol is precise for loadable families
    
    # Convert to list
    instances = [i for i in instance_collector]
    
    if not instances:
        forms.alert("No instances of '{}' found in the project.".format(selected_name), exitscript=True)
        
    return instances

def main():
    # 0. Ask for Selection Mode
    options = ['Current Selection', 'Select by Family Type']
    switch = forms.CommandSwitchWindow.show(
        options,
        message='How do you want to select elements?'
    )
    
    if not switch:
        return

    # 1. Get Elements based on choice
    elements = []
    if switch == 'Current Selection':
        elements = get_elements_by_selection()
    elif switch == 'Select by Family Type':
        elements = get_elements_by_family_type()
    
    if not elements:
        return # Should have been handled, but safety check

    print("Processing {} elements...".format(len(elements)))
    
    # 2. Prompt for Parameter Names via Dropdowns
    # Harvest parameters from the first element
    if not elements:
        return
        
    sample_el = elements[0]
    
    # Collect all params
    # We use a dict to map Name -> Definition to handle case sensitivity if needed, 
    # but simple names are usually enough for Lookup.
    # Note: Parameters is an Iterator.
    params = set()
    writable_params = set()
    
    for p in sample_el.Parameters:
        p_name = p.Definition.Name
        params.add(p_name)
        if not p.IsReadOnly:
            writable_params.add(p_name)
            
    sorted_params = sorted(list(params))
    sorted_writable = sorted(list(writable_params))
    
    # Ask for Source
    source_param_name = forms.SelectFromList.show(
        sorted_params,
        title="Select Source Parameter (Get Value From)",
        multiselect=False
    )
    
    if not source_param_name:
        return

    # Ask for Target
    # We ideally only show writable params for target, but sometimes 
    # API flags are tricky, so showing all is safer, but let's try writable first.
    # Or just show all to avoid confusion if API thinks it's read-only but it isn't.
    # Let's show all but maybe mark them? No, simple is best.
    target_param_name = forms.SelectFromList.show(
        sorted_params, 
        title="Select Target Parameter (Set Value To)",
        multiselect=False
    )
    
    if not target_param_name:
        return

    # 3. Transaction
    t = DB.Transaction(doc, "Transfer Parameter Values")
    t.Start()
    
    success_count = 0
    fail_count = 0
    
    for el in elements:
        try:
            # Get Parameters
            p_source = el.LookupParameter(source_param_name)
            p_target = el.LookupParameter(target_param_name)
            
            # Validation
            if not p_source:
                print("Element {}: Source parameter '{}' not found.".format(el.Id, source_param_name))
                fail_count += 1
                continue
                
            if not p_target:
                print("Element {}: Target parameter '{}' not found.".format(el.Id, target_param_name))
                fail_count += 1
                continue
                
            if p_target.IsReadOnly:
                print("Element {}: Target parameter '{}' is read-only.".format(el.Id, target_param_name))
                fail_count += 1
                continue
            
            # Get Value Logic
            val = None
            if p_source.StorageType == DB.StorageType.String:
                val = p_source.AsString()
            elif p_source.StorageType == DB.StorageType.Double:
                val = p_source.AsDouble()
            elif p_source.StorageType == DB.StorageType.Integer:
                val = p_source.AsInteger()
            elif p_source.StorageType == DB.StorageType.ElementId:
                val = p_source.AsElementId()
            
            # Set Value Logic
            if val is not None:
                if p_target.StorageType == DB.StorageType.String:
                     if p_source.StorageType != DB.StorageType.String:
                         # Attempt to use AsValueString for formatted value, else raw conversion
                         formatted = p_source.AsValueString()
                         p_target.Set(formatted if formatted else str(val))
                     else:
                         p_target.Set(val)
                else:
                    p_target.Set(val)
                success_count += 1
            else:
                 # Source parameter exists but is empty/None
                 # Optionally clear target? For now, we just skip or maybe we should set to null?
                 # Let's count as fail/skip to avoid accidental data loss unless requested.
                 print("Element {}: Source value is null/empty.".format(el.Id))
                 fail_count += 1

        except Exception as e:
            print("Element {}: Error - {}".format(el.Id, e))
            fail_count += 1

    t.Commit()
    
    # 4. Report
    print("--------------------------")
    print("Transfer Complete.")
    print("Success: {}".format(success_count))
    print("Failed: {}".format(fail_count))

if __name__ == '__main__':
    main()
