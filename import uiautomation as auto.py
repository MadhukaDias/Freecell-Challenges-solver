import uiautomation as auto
import time

def walk_control(control, depth=0):
    indent = "  " * depth
    try:
        name = control.Name
        print(f"{indent}{control.ControlTypeName}: '{name}'")
    except:
        pass
    
    if depth < 10: # Limit depth
        for child in control.GetChildren():
            walk_control(child, depth + 1)

def main():
    print("Searching for Solitaire window...")
    window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
    if window.Exists(0, 1):
        print("Found window. Dumping controls...")
        walk_control(window)
    else:
        print("Solitaire window not found.")

if __name__ == "__main__":
    main()
