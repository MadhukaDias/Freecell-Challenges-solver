import uiautomation as auto
import re
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# --- CONFIGURATION & MAPPINGS ---

NAME_TO_RANK = {
    'Ace': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5, 'Six': 6,
    'Seven': 7, 'Eight': 8, 'Nine': 9, 'Ten': 10, 'Jack': 11, 'Queen': 12, 'King': 13
}
NAME_TO_SUIT = {
    'Hearts': 'h', 'Clubs': 'c', 'Diamonds': 'd', 'Spades': 's'
}

RANK_TO_CODE = {
    1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 't', 11: 'j', 12: 'q', 13: 'k'
}

COLUMN_PREFIXES = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"]

# --- CARD PARSING ---

def parse_card_name(name):
    """Parse card name and return (rank, suit) tuple"""
    if not name or "empty" in name.lower():
        return None
    match = re.search(r"(Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King) of (Hearts|Clubs|Diamonds|Spades)", name)
    if match:
        rank_str, suit_str = match.groups()
        return (NAME_TO_RANK[rank_str], NAME_TO_SUIT[suit_str])
    return None

def get_sorted_children(control):
    """Get children controls sorted by left position"""
    if not control.Exists(0, 0):
        return []
    children = control.GetChildren()
    children.sort(key=lambda c: c.BoundingRectangle.left)
    return children

# --- DECK CAPTURE ---

def capture_deck():
    """Captures the current freecell deck configuration and returns it as a dictionary"""
    # Connect to Solitaire Window
    window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
    if not window.Exists(0, 1):
        print("Error: Solitaire window not found")
        return None
    
    # Connect to Groups
    tableau_group = window.GroupControl(AutomationId="Group_Tableau")
    freecell_group = window.GroupControl(AutomationId="Group_Free")
    foundation_group = window.GroupControl(AutomationId="Group_Foundation")

    deck_state = {
        "freecells": [],
        "foundation": [],
        "tableau": []
    }

    # 1. READ FREECELLS
    fc_elements = get_sorted_children(freecell_group)
    for cell in fc_elements:
        card_val = parse_card_name(cell.Name)
        if not card_val:
            kids = cell.GetChildren()
            if kids:
                card_val = parse_card_name(kids[0].Name)
        deck_state["freecells"].append(card_val)

    # 2. READ FOUNDATIONS
    found_elements = get_sorted_children(foundation_group)
    for pile in found_elements:
        card_val = parse_card_name(pile.Name)
        if not card_val:
            kids = pile.GetChildren()
            if kids:
                card_val = parse_card_name(kids[-1].Name)
        deck_state["foundation"].append(card_val)

    # 3. READ TABLEAU
    tab_stacks = get_sorted_children(tableau_group)
    for stack in tab_stacks:
        col_cards = []
        card_elements = get_sorted_children(stack)
        card_elements.sort(key=lambda c: c.BoundingRectangle.top)
        
        for card_el in card_elements:
            val = parse_card_name(card_el.Name)
            if val:
                col_cards.append(val)
        deck_state["tableau"].append(col_cards)

    return deck_state

def encode_card(card_tuple):
    """Convert card tuple to encoded string"""
    if card_tuple is None:
        return "00"
    rank_int, suit_char = card_tuple
    return f"{RANK_TO_CODE[rank_int]}{suit_char}"

def encode_deck(deck_state):
    """Encode deck state to solver-compatible string format"""
    # 1. Freecells
    fc_str = ""
    current_fcs = deck_state['freecells']
    for i in range(4):
        if i < len(current_fcs):
            fc_str += encode_card(current_fcs[i])
        else:
            fc_str += "00"

    # 2. Foundation
    fo_str = ""
    current_fos = deck_state['foundation']
    for i in range(4):
        if i < len(current_fos):
            fo_str += encode_card(current_fos[i])
        else:
            fo_str += "00"

    # 3. Tableau
    tab_str = ""
    for idx, column in enumerate(deck_state['tableau']):
        if idx < 8:
            prefix = COLUMN_PREFIXES[idx]
            tab_str += prefix
            for card in column:
                tab_str += encode_card(card)

    return fc_str + fo_str + tab_str

def main():
    """Main function to capture and display deck configuration"""
    print("Capturing Freecell Deck...")
    
    deck_state = capture_deck()
    
    if deck_state:
        print("\n--- Captured Deck State ---")
        print(f"Freecells: {deck_state['freecells']}")
        print(f"Foundation: {deck_state['foundation']}")
        print(f"Tableau:")
        for idx, col in enumerate(deck_state['tableau']):
            print(f"  Column {idx + 1}: {col}")
        
        encoded = encode_deck(deck_state)
        print(f"\n--- Encoded Deck Configuration ---")
        print(encoded)
        
        return encoded
    else:
        print("Failed to capture deck")
        return None

if __name__ == "__main__":
    main()
