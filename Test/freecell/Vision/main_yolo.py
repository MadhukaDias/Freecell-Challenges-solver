import cv2
import numpy as np
from ultralytics import YOLO
import itertools
from collections import defaultdict
from ImageGet import RegionSelector

# --- CONFIGURATION ---
# 1. Ambiguity Mapping: Defines what a generic class could be
AMBIGUITY_MAP = {
    '1_red': ['1h', '1d'], '1_black': ['1c', '1s'],
    '2_red': ['2h', '2d'], '2_black': ['2c', '2s'],
    '3_red': ['3h', '3d'], '3_black': ['3c', '3s'],
    '4_red': ['4h', '4d'], '4_black': ['4c', '4s'],
    '5_red': ['5h', '5d'], '5_black': ['5c', '5s'],
    '6_red': ['6h', '6d'], '6_black': ['6c', '6s'],
    '7_red': ['7h', '7d'], '7_black': ['7c', '7s'],
    '8_red': ['8h', '8d'], '8_black': ['8c', '8s'],
    '9_red': ['9h', '9d'], '9_black': ['9c', '9s'],
    't_red': ['th', 'td'], 't_black': ['tc', 'ts'],
    'j_red': ['jh', 'jd'], 'j_black': ['jc', 'js'],
    'q_red': ['qh', 'qd'], 'q_black': ['qc', 'qs'],
    'k_red': ['kh', 'kd'], 'k_black': ['kc', 'ks'],
}

# 2. All possible specific cards (for validation)
ALL_CARDS = set()
for variants in AMBIGUITY_MAP.values():
    for card in variants:
        ALL_CARDS.add(card)

class SolitaireSolverYOLO:
    def __init__(self, model_path='best.pt'):
        print(f"Loading YOLO model from {model_path}...")
        self.model = YOLO(model_path)
        
    def detect_and_process(self, image_path, output_image_path="yolo_output.jpg"):
        """
        Main function to Detect -> Sort -> Deduce -> Encode.
        """
        # 1. Run Inference
        results = self.model(image_path, imgsz=640, conf=0.51, iou=0.45)
        result = results[0]
        
        # Save the visualization directly from YOLO
        result.save(filename=output_image_path)
        print(f"Debug image saved to {output_image_path}")

        # 2. Extract Data
        img_h, img_w = result.orig_shape
        detections = []
        
        for box in result.boxes:
            coords = box.xyxy[0].tolist() # x1, y1, x2, y2
            cx = (coords[0] + coords[2]) / 2
            cy = (coords[1] + coords[3]) / 2
            
            class_id = int(box.cls[0])
            name = self.model.names[class_id]
            
            detections.append({
                'name': name,
                'cx': cx,
                'cy': cy,
                'x': coords[0], # Top-left X (good for sorting)
                'y': coords[1]  # Top-left Y
            })

        # 3. Spatially Organize (Freecell vs Foundation vs Tableau)
        board_state = self.organize_board(detections, img_w, img_h)
        
        # 4. Resolve Ambiguities (The Deduction Logic)
        possible_configurations = self.resolve_ambiguities(board_state)
        
        # 5. Generate Encoded Strings
        encoded_results = []
        for config in possible_configurations:
            enc_str = self.generate_string(config)
            encoded_results.append(enc_str)
            
        return encoded_results

    def organize_board(self, detections, width, height):
        """
        Sorts raw detections into game slots based on coordinates.
        Using percentages to make it resolution-independent.
        """
        freecells = []   # List of card names
        foundations = [] # List of card names
        tableau = [[] for _ in range(8)] # 8 Columns
        
        # Y-Threshold: Top 25% is usually the header row
        header_cutoff = height * 0.25
        center_x = width / 2
        
        # Determine specific empty slots vs cards
        # We need to preserve the order (Left to Right) for header
        
        header_items = []
        
        for item in detections:
            # Check if Top Row
            if item['cy'] < header_cutoff:
                header_items.append(item)
            else:
                # Tableau Logic (Columns)
                col_width = width / 8
                col_idx = int(item['cx'] // col_width)
                col_idx = max(0, min(col_idx, 7)) # Clamp 0-7
                
                # If it's an 'empty_tableau' marker, we ignore it for the list
                # (Unless you want to explicitly track empty cols, but empty list implies it)
                if item['name'] != 'empty_tableau':
                    tableau[col_idx].append(item)

        # Sort Header Items Left to Right
        header_items.sort(key=lambda x: x['cx'])
        
        # Split Header into Freecell (Left) and Foundation (Right)
        # Note: We rely on X position relative to center
        for item in header_items:
            # Handle Empty Slot Markers
            val = item['name']
            if val == 'empty_freecell': val = '00'
            if val == 'empty_foundation': val = '00'
            
            if item['cx'] < center_x:
                freecells.append(val)
            else:
                foundations.append(val)
                
        # Fill missing slots if detection missed 'empty' markers
        # (Freecell and Foundation must have 4 items each)
        while len(freecells) < 4: freecells.append('00')
        while len(foundations) < 4: foundations.append('00')
        
        # Trim if YOLO Hallucinated extra slots (keep 4 closest to expected centers)
        freecells = freecells[:4]
        foundations = foundations[:4]

        # Sort Tableau Columns Top to Bottom
        clean_tableau = []
        for col in tableau:
            col.sort(key=lambda x: x['y'])
            col_names = [c['name'] for c in col]
            clean_tableau.append(col_names)

        return {
            'freecells': freecells,
            'foundations': foundations,
            'tableau': clean_tableau
        }

    def resolve_ambiguities(self, board_state):
        """
        Logic to solve 't_black' vs 'tc'.
        Returns a list of full resolved board states (dictionaries).
        """
        
        # Flatten board to list all detected items
        all_items = []
        all_items.extend(board_state['freecells'])
        all_items.extend(board_state['foundations'])
        for col in board_state['tableau']:
            all_items.extend(col)
            
        # 1. Identify what is FIXED (Specific cards like 'kh', '10s')
        fixed_cards = set()
        ambiguous_indices = [] # Stores (location_type, index1, index2, value)
        
        for i, card in enumerate(all_items):
            if card in ALL_CARDS:
                fixed_cards.add(card)
            elif card in AMBIGUITY_MAP:
                # It is ambiguous (e.g. 'k_red')
                ambiguous_indices.append((i, card))
                
        # If no ambiguities, return strictly one result
        if not ambiguous_indices:
            return [board_state]
            
        print(f"Resolving {len(ambiguous_indices)} ambiguous cards...")

        # 2. Generate Possibilities
        # For every ambiguous card (e.g. 't_black'), possibilities are ['tc', 'ts']
        # We filter these: if 'tc' is in fixed_cards, then it MUST be 'ts'.
        
        possibility_space = []
        
        for idx, amb_name in ambiguous_indices:
            candidates = AMBIGUITY_MAP[amb_name] # e.g. ['tc', 'ts']
            valid_candidates = [c for c in candidates if c not in fixed_cards]
            
            if not valid_candidates:
                # Critical Error: Both options already exist on board? 
                # YOLO hallucination or game error. Fallback to generic.
                print(f"Warning: Impossible ambiguity for {amb_name}. Both candidates taken.")
                valid_candidates = candidates # Reset to allow output (even if wrong)
                
            possibility_space.append(valid_candidates)

        # 3. Create Permutations (Cartesian Product)
        # If we have [ ['tc'], ['kd', 'kh'] ], this generates valid combinations
        # We must ensure no duplicates in a single permutation (can't have two 'kh')
        
        valid_boards = []
        
        for p in itertools.product(*possibility_space):
            # p is a tuple of guesses, e.g., ('tc', 'kd')
            
            # Check for duplicates within this guess + fixed cards
            combined_set = set(fixed_cards)
            is_valid = True
            for card in p:
                if card in combined_set:
                    is_valid = False # Duplicate found in this permutation
                    break
                combined_set.add(card)
            
            if is_valid:
                # Reconstruct the board with these specific choices
                new_state = self.apply_permutation(board_state, ambiguous_indices, p)
                valid_boards.append(new_state)

        return valid_boards

    def apply_permutation(self, original_state, indices_map, choices):
        """Helper to inject specific resolved cards back into the board structure."""
        # Deep copy structure
        import copy
        new_state = copy.deepcopy(original_state)
        
        # Flatten again to access by index
        # Note: This relies on strictly deterministic ordering, matching resolve_ambiguities
        flat_refs = []
        
        # Map references to the mutable lists in new_state
        for i in range(len(new_state['freecells'])):
            flat_refs.append((new_state['freecells'], i))
        for i in range(len(new_state['foundations'])):
            flat_refs.append((new_state['foundations'], i))
        for col in new_state['tableau']:
            for i in range(len(col)):
                flat_refs.append((col, i))
                
        # Apply choices
        for (tuple_idx, _), choice_val in zip(indices_map, choices):
            target_list, target_idx = flat_refs[tuple_idx]
            target_list[target_idx] = choice_val
            
        return new_state

    def generate_string(self, state):
        """Converts state dict to the encoded string format."""
        encoded_str = ""
        
        # 1. Freecells
        for c in state['freecells']:
            encoded_str += c
            
        # 2. Foundations
        for c in state['foundations']:
            encoded_str += c
            
        # 3. Tableau
        roman = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii']
        for idx, col in enumerate(state['tableau']):
            encoded_str += roman[idx]
            for c in col:
                encoded_str += c
                
        return encoded_str

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("Starting Freecell Vision Solver...")
    # Point to your trained model
    solver = SolitaireSolverYOLO(model_path='C:/Users/madhu/Desktop/Freecell solver/runs/detect/train3/weights/best.pt')
    
    print("Please select the region to capture...")
    selector = RegionSelector()
    img_path = selector.run()
    
    if img_path:
        print(f"Captured image: {img_path}")
        print("Processing with YOLO...")
        try:
            results = solver.detect_and_process(img_path)
            
            print("\n--- RESULTS ---")
            if len(results) == 1:
                print("Deterministic Match Found:")
                print(results[0])
            else:
                print(f"Ambiguity Detected. Found {len(results)} possible configurations:")
                for i, res in enumerate(results):
                    print(f"Option {i+1}: {res}")
                    
        except Exception as e:
            print(f"Error during processing: {e}")
    else:
        print("No image captured. Exiting.")