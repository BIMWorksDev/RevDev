#! ironpython
# -*- coding: utf-8 -*-

from pyrevit import revit, DB, UI, forms, script

doc = revit.doc
uidoc = revit.uidoc

class GridSelectionFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, DB.Grid)

    def AllowReference(self, reference, point):
        return False

def main():
    active_view = doc.ActiveView
    
    # Check if we are in a graphical view
    if not isinstance(active_view, (DB.ViewPlan, DB.ViewSection)):
        forms.alert("Active view must be a Plan, Section, or Elevation view.", exitscript=True)

    # Prompt user to select grids
    try:
        grid_filter = GridSelectionFilter()
        references = uidoc.Selection.PickObjects(
            UI.Selection.ObjectType.Element, 
            grid_filter,
            "Select Grids to toggle bubble side"
        )
    except Exception:
        # User likely pressed Escape
        return

    if not references:
        return

    # Process grids in a transaction
    with revit.Transaction("Toggle Grid Bubbles"):
        for ref in references:
            grid = doc.GetElement(ref.ElementId)
            
            end0 = DB.DatumEnds.End0
            end1 = DB.DatumEnds.End1
            
            vis0 = grid.IsBubbleVisibleInView(end0, active_view)
            vis1 = grid.IsBubbleVisibleInView(end1, active_view)
            
            if vis0:
                grid.HideBubbleInView(end0, active_view)
            else:
                grid.ShowBubbleInView(end0, active_view)
                
            if vis1:
                grid.HideBubbleInView(end1, active_view)
            else:
                grid.ShowBubbleInView(end1, active_view)

    print("Successfully toggled bubbles for {} grids.".format(len(references)))

if __name__ == '__main__':
    main()
