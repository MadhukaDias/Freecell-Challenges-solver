#include <algorithm>
#include <atomic>
#include <memory>
#include <mutex>
#include <thread>
#include <iostream>
#include <sstream>
#include <fstream>
using namespace std;

#include "bucket.h"
#include "hash_table.h"
#include "node.h"
#include "options.h"

class Beam {
 public:
  Beam(int seed, int beam_size, int beam_id, int num_beams);
  string Solve(const Node& layout);
  void SubmitWork(List<Node>* new_work);

 private:
  Node* CreateNewLevel(const Bucket& cur_level, Bucket* new_level);
  Node* BeamSearch(const Node& layout);
  string EncodeSolution(const Node& start, const Node& finish) const;

  List<Node> GetWork();
  Node* ProcessNewNodes(List<Node> new_nodes, Bucket* new_level);
  int TargetBeam(unsigned hash) const {
    // Shift bits so hash table can be better used.
    return (hash + (hash >> 24)) % num_beams_;
  }

  void EnterBarrier();
  bool BarrierDone();
  void Barrier();
  bool AllBeamsEmpty(int level) const;

  const int seed_;
  const int beam_size_;
  const int beam_id_;
  const int num_beams_;

  int upperbound_ = kMaxMoves + 1;
  vector<Bucket> levels_;
  std::unique_ptr<HashTable> hash_table_;
  Node shared_solution_;  // to be shared with other beams
  mutable Pool pool_;

  int sequence_number_;
  std::atomic<int> barrier_;

  List<Node> work_;
  std::mutex mu_;
};

vector<std::unique_ptr<Beam>> beams;

Beam::Beam(int seed, int beam_size, int beam_id, int num_beams)
    : seed_(seed),
      beam_size_(beam_size),
      beam_id_(beam_id),
      num_beams_(num_beams),
      sequence_number_(0),
      barrier_(0) {
  const int kNumBins = (kMaxMoves - kMinMoves) * 2;
  for (int i = 0; i < kMaxMoves; ++i) levels_.emplace_back(Bucket(kNumBins));
  hash_table_.reset(new HashTable(beam_size_ * 2));
}

void Beam::SubmitWork(List<Node>* new_work) {
  if (new_work->empty()) return;
  mu_.lock();
  work_.Append(new_work);
  mu_.unlock();
}

List<Node> Beam::GetWork() {
  List<Node> new_work;
  mu_.lock();
  new_work.Append(&work_);
  mu_.unlock();
  return new_work;
}

void Beam::EnterBarrier() {
  sequence_number_ = !sequence_number_;
  if (beam_id_ != 0) barrier_ = sequence_number_;
}

bool Beam::BarrierDone() {
  if (beam_id_ == 0) {
    for (int i = 1; i < num_beams_; ++i)
      if (beams[i]->barrier_ != sequence_number_) return false;
    beams[0]->barrier_ = sequence_number_;
    return true;
  } else
    return (beams[0]->barrier_ == sequence_number_);
}

void Beam::Barrier() {
  EnterBarrier();
  while (!BarrierDone()) sched_yield();
}

bool Beam::AllBeamsEmpty(int level) const {
  for (int i = 0; i < num_beams_; ++i)
    if (beams[i]->levels_[level].size() > 0) return false;
  return true;
}

Node* Beam::CreateNewLevel(const Bucket& cur_level, Bucket* new_level) {
  vector<List<Node>> partitions(num_beams_);
  ScopedNode solution(&pool_);

  auto process_new_solution = [&](Node* new_solution) {
    if (!new_solution) return;
    solution.reset(new_solution);
    if (num_beams_ == 1) return;

    // If solution is produced by this beam, send it to other beams to lower
    // their upperbounds.
    if (TargetBeam(solution->hash()) == beam_id_) {
      for (int i = 0; i < num_beams_; ++i) {
        if (i == beam_id_) continue;
        partitions[i].Append(pool_.New(*solution));
      }
    }
  };

  int expand_count = 0;
  cur_level.Iterate([&](Node* node) {
    if (node->moves_performed() >= upperbound_ - 1) return;
    auto new_nodes = node->Expand(&pool_);
    if (new_nodes.empty()) return;

    if (num_beams_ == 1) {
      for (auto* node : new_nodes) node->ComputeHash();
      process_new_solution(ProcessNewNodes(new_nodes, new_level));
    } else {
      for (auto* node : new_nodes) {
        node->ComputeHash();
        partitions[TargetBeam(node->hash())].Append(node);
      }
      if (++expand_count < 100) return;
      expand_count = 0;
      for (int i = 0; i < num_beams_; ++i) beams[i]->SubmitWork(&partitions[i]);
      process_new_solution(ProcessNewNodes(GetWork(), new_level));
    }
  });
  if (num_beams_ > 1) {
    for (int i = 0; i < num_beams_; ++i) beams[i]->SubmitWork(&partitions[i]);
    EnterBarrier();
    while (!BarrierDone())
      process_new_solution(ProcessNewNodes(GetWork(), new_level));
    for (int round = 0; round < 2; ++round) {
      for (int i = 0; i < num_beams_; ++i) beams[i]->SubmitWork(&partitions[i]);
      Barrier();
      process_new_solution(ProcessNewNodes(GetWork(), new_level));
    }
    assert(work_.empty());
    for (int i = 0; i < num_beams_; ++i) assert(partitions[i].empty());
    Barrier();
  }

  // hash_table_->Show(beam_id_);
  // cur_level.Iterate([&](Node* node) { hash_table_->Remove(node); });
  return solution.release();
}

bool CheckChallenge(const Node* node, const string& code) {
    if (code == "00") return node->cards_unsorted() == 0;
    
    if (code.length() == 2) {
        char rank_char = code[0];
        char type_char = code[1];
        
        // Parse Rank
        int rank = -1;
        if (isdigit(rank_char)) {
            rank = rank_char - '0';
        } else {
            char lower_r = tolower(rank_char);
            if (lower_r == 't') rank = 10;
            else if (lower_r == 'j') rank = 11;
            else if (lower_r == 'q') rank = 12;
            else if (lower_r == 'k') rank = 13;
            else if (lower_r == 'a') rank = 1;
        }
        
        if (rank > 0) {
            int target_rank0 = rank - 1; // 0-based

            // Case 1: Specific Suit (e.g. 'kd' -> King Diamonds)
            if (isalpha(type_char)) {
                int suit = -1;
                char s = tolower(type_char);
                if (s == 'c') suit = CLUB;
                else if (s == 'd') suit = DIAMOND;
                else if (s == 'h') suit = HEART;
                else if (s == 's') suit = SPADE;
                
                if (suit != -1) {
                    bool has = node->GetFoundation(suit).Has(Card(suit, target_rank0));
                    if (has) cout << "Challenge Met: " << code << endl;
                    return has;
                }
            } 
            // Case 2: Count (e.g. 'k4' -> 4 Kings)
            else if (isdigit(type_char)) {
                int count_req = type_char - '0';
                int current_count = 0;
                for(int s=0; s<4; ++s) {
                    // Check if foundation size > target_rank0 means it contains 0..target_rank0
                    if (node->GetFoundation(s).size() > target_rank0) {
                        current_count++;
                    }
                }
                if (current_count >= count_req) {
                     cout << "Challenge Met: " << code << " (" << current_count << "/" << count_req << ")" << endl;
                     return true;
                }
                return false;
            }
        }
    }
    
    return false;
}

Node* Beam::ProcessNewNodes(List<Node> new_nodes, Bucket* new_level) {
  ScopedNode solution(&pool_);
  for (auto* new_node : new_nodes) {
    
    // 1. Check Move Limit First
    if (options.move_limit > 0) {
        if (new_node->moves_performed() > options.move_limit) {
            pool_.Delete(new_node);
            continue; 
        }
    }

    // 2. Optimization: Prune if already worse than known solution
    if (new_node->min_total_moves() >= upperbound_ ||
        new_node->bin() < new_level->lowerbound()) {
      pool_.Delete(new_node);
      continue;
    }
    
    // 3. Check Challenge Condition
    if (options.challenge_code != "00") {
        if (CheckChallenge(new_node, options.challenge_code) && new_node->min_total_moves() < upperbound_) {
            solution.reset(new_node);
            upperbound_ = solution->min_total_moves();
            continue;
        }
    } else {
        // Standard full solve check
         if (new_node->cards_unsorted() == 0 && new_node->min_total_moves() < upperbound_) {
             solution.reset(new_node);
             upperbound_ = solution->min_total_moves();
             continue;
         }
    }

    if ((new_level->size() == beam_size_ &&
         new_node->bin() > new_level->max()) ||
        hash_table_->Find(new_node)) {
      pool_.Delete(new_node);
    } else if (new_level->size() < beam_size_) {
      new_level->Add(new_node, new_node->bin());
      hash_table_->Add(new_node);
    } else {
      auto max_node = new_level->RemoveMax();
      hash_table_->Remove(max_node);
      pool_.Delete(max_node);
      new_level->Add(new_node, new_node->bin());
      hash_table_->Add(new_node);
    }
  }
  return solution.release();
}

Node* Beam::BeamSearch(const Node& layout) {
  auto root = pool_.New(layout);
  root->ComputeHash();
  levels_[0].Add(root, root->bin());
  hash_table_->Add(root);

  ScopedNode solution(&pool_);
  int max_level_size = 0;
  for (int i = 0; i < kMaxMoves; ++i) {
    if (num_beams_ == 1) {
      if (levels_[i].empty()) break;
    } else {
      Barrier();
      if (AllBeamsEmpty(i)) break;
      Barrier();
    }
    if (beam_id_ == 0 && !options.quiet) {
      char progress[30];
      sprintf(progress, "%s%4d %8d", string('\b', 13).c_str(), i,
              levels_[i].size());
      printf("%s", progress);
      fflush(stdout);
      max_level_size = max(max_level_size, levels_[i].size());
    }
    auto new_solution = CreateNewLevel(levels_[i], &levels_[i + 1]);
    if (new_solution) solution.reset(new_solution);
    constexpr int kPreservedLevels = 1;
    if (i >= kPreservedLevels) {
      bool first = true;
      levels_[i - kPreservedLevels].Iterate([&](Node* node) {
#if 0
        if (i == 75 && first) {
          first = false;
          node->Show();
          auto code = EncodeSolution(layout, *node);
          puts(code.c_str());
        }
#endif
        hash_table_->Remove(node);
        pool_.Delete(node);
      });
      levels_[i - kPreservedLevels].Clear();
    }
  }
  for (auto& level : levels_) {
    level.Iterate([&](Node* node) {
      hash_table_->Remove(node);
      pool_.Delete(node);
    });
    level.Clear();
  }
  if (beam_id_ == 0 && !options.quiet) {
    printf("%s%8d\n", string('\b', 8).c_str(), max_level_size);
  }
  return solution.release();
}

string Beam::EncodeSolution(const Node& start, const Node& finish) const {
  string code;
  ScopedNode node(&pool_, pool_.New(start));
  Node::CompressedMoves::Reader reader(finish.moves());
  
  if (!options.quiet) cout << "EncodeSolution: moves_performed=" << finish.moves_performed() << " Unsorted=" << finish.cards_unsorted() << endl;

  for (int i = 0; i < finish.moves_performed(); ++i) {
    if (node->cards_unsorted() == 0) {
      if (!options.quiet) cout << "EncodeSolution: Node solved at step " << i << ". Calling CompleteSolution." << endl;
      code += node->CompleteSolution();
      break;
    }

    auto new_nodes = node->Expand(&pool_).ToVector();
    int move_index = reader.Read(new_nodes.size());
    assert(move_index < new_nodes.size());
    auto picked_node = new_nodes[move_index];
    for (auto* new_node : new_nodes)
      if (new_node != picked_node) pool_.Delete(new_node);
    node.reset(picked_node);
    code += node->last_move().Encode();
  }
  if (!options.quiet) cout << "EncodeSolution: Generated code length=" << code.length() << endl;
  return code;
}

string Beam::Solve(const Node& layout) {
  upperbound_ = kMaxMoves;
  if (beam_id_ == 0 && !options.quiet) printf("upperbound %d\n", upperbound_);
  
  ScopedNode solution(&pool_, BeamSearch(layout));
  string coded_solution;

  if (solution) {
      if (num_beams_ > 1) {
        // Use the same one solution in case different ones are found.
        if (beam_id_ == 0) new (&shared_solution_) Node(*solution);
        Barrier();
        if (beam_id_ != 0) solution.reset(new Node(beams[0]->shared_solution_));
        Barrier();
      }

      if (beam_id_ == 0 && !options.quiet) solution->ShowSummary();
      coded_solution = EncodeSolution(layout, *solution);
  } else {
      if (beam_id_ == 0 && !options.quiet) printf("No solution found by BeamSearch.\n");
  }
  
  // if (beam_id_ == 0) printf("%d:%s\n", seed_, coded_solution.c_str());
  return coded_solution;
}


Card ParseCard(string s) {
    int rank = -1;
    int suit = -1;
    char suitChar = s.back();
    string rankStr = s.substr(0, s.length() - 1);

    if (rankStr == "A") rank = ACE;
    else if (rankStr == "2") rank = R2;
    else if (rankStr == "3") rank = R3;
    else if (rankStr == "4") rank = R4;
    else if (rankStr == "5") rank = R5;
    else if (rankStr == "6") rank = R6;
    else if (rankStr == "7") rank = R7;
    else if (rankStr == "8") rank = R8;
    else if (rankStr == "9") rank = R9;
    else if (rankStr == "10" || rankStr == "T") rank = R10;
    else if (rankStr == "J") rank = RJ;
    else if (rankStr == "Q") rank = RQ;
    else if (rankStr == "K") rank = KING;

    if (suitChar == 'S') suit = SPADE;
    else if (suitChar == 'H') suit = HEART;
    else if (suitChar == 'D') suit = DIAMOND;
    else if (suitChar == 'C') suit = CLUB;

    return Card(suit, rank);
}

Card ParseCleanCard(string s) {
    // s is like "8s", "tc", "1d"
    if (s.length() < 2) return Card(0, 0); // Error
    
    char rankChar = s[0];
    char suitChar = s[1];
    
    int rank = -1;
    int suit = -1;

    if (rankChar == '1') rank = ACE;
    else if (rankChar == '2') rank = R2;
    else if (rankChar == '3') rank = R3;
    else if (rankChar == '4') rank = R4;
    else if (rankChar == '5') rank = R5;
    else if (rankChar == '6') rank = R6;
    else if (rankChar == '7') rank = R7;
    else if (rankChar == '8') rank = R8;
    else if (rankChar == '9') rank = R9;
    else if (rankChar == 't') rank = R10;
    else if (rankChar == 'j') rank = RJ;
    else if (rankChar == 'q') rank = RQ;
    else if (rankChar == 'k') rank = KING;

    if (suitChar == 's') suit = SPADE;
    else if (suitChar == 'h') suit = HEART;
    else if (suitChar == 'd') suit = DIAMOND;
    else if (suitChar == 'c') suit = CLUB;

    return Card(suit, rank);
}

// Helper to strip ANSI codes for file output
string StripAnsi(const string& str) {
    string res = "";
    bool in_ansi = false;
    for (char c : str) {
        if (c == '\033') {
            in_ansi = true;
        } else if (in_ansi && c == 'm') {
            in_ansi = false;
        } else if (!in_ansi) {
            res += c;
        }
    }
    return res;
}

void DecodeAndShow(string solution_str, Node layout) {
    // printf("readable solution\n");
    int step = 1;
    int pos = 0;
    while (pos < solution_str.length()) {
        // 1. Parse Card
        string card_code = solution_str.substr(pos, 2);
        pos += 2;
        
        // 2. Parse Stack Count
        int stack_count = 1;
        if (pos < solution_str.length() && solution_str[pos] == '#') {
            pos++; // skip '#'
            size_t next_underscore = solution_str.find('_', pos);
            string count_str = solution_str.substr(pos, next_underscore - pos);
            stack_count = stoi(count_str);
            pos = next_underscore;
        }

        // 3. Skip '_'
        if (pos < solution_str.length() && solution_str[pos] == '_') pos++;

        // 4. Parse Source
        string source_code;
        if (pos < solution_str.length()) {
            source_code = solution_str[pos];
            pos++;
        }

        // 5. Skip '_'
        if (pos < solution_str.length() && solution_str[pos] == '_') pos++;

        // 6. Parse Dest
        string dest_code;
        if (pos < solution_str.length()) {
            if (solution_str[pos] == '~') {
                // ~n~
                size_t end_tilde = solution_str.find('~', pos + 1);
                dest_code = solution_str.substr(pos, end_tilde - pos + 1);
                pos = end_tilde + 1;
            } else {
                // F or R
                dest_code = solution_str[pos];
                pos++;
            }
        }

        // Prepare readable strings
        string card_name = "";
        string clean_card_code = card_code;
        // Uppercase for display
        for(char &c : card_code) c = toupper(c);
        
        // Colorize card_code
        string colored_card_code = card_code;
        char suit = card_code.back();
        if (suit == 'H' || suit == 'D') {
            colored_card_code = "\033[31m" + card_code + "\033[0m"; // Red
        } else if (suit == 'S' || suit == 'C') {
            colored_card_code = "\033[32m" + card_code + "\033[0m"; // Green
        }

        if (stack_count > 1) {
            card_name = "stack of " + to_string(stack_count) + " cards (" + colored_card_code + ")";
        } else {
            card_name = colored_card_code;
        }

        string source_name = "";
        int src_idx = -1;
        bool src_is_reserve = false;
        if (source_code == "R") {
            source_name = "Reserve";
            src_is_reserve = true;
        } else {
            src_idx = stoi(source_code);
            source_name = "Tableau " + to_string(src_idx + 1);
        }

        string dest_name = "";
        string on_card = "";
        int dest_idx = -1;
        bool dest_is_foundation = false;
        bool dest_is_reserve = false;
        
        if (dest_code == "F") {
            dest_name = "Foundation";
            dest_is_foundation = true;
        } else if (dest_code == "R") {
            dest_name = "Reserve";
            dest_is_reserve = true;
        } else {
            // ~n~
            string n_str = dest_code.substr(1, dest_code.length() - 2);
            dest_idx = stoi(n_str);
            dest_name = "Tableau " + to_string(dest_idx + 1);
        }

        // Determine "on card"
        if (dest_idx != -1) {
            if (layout.GetTableau(dest_idx).empty()) {
                on_card = " (empty column)";
            } else {
                on_card = " (on " + string(layout.GetTableau(dest_idx).Top().ToString()) + ")";
            }
        }

        // Check for Auto Move
        bool is_auto = false;
        Card c_obj = ParseCleanCard(clean_card_code);
        if (dest_is_foundation && layout.CanAutoPlay(c_obj)) {
            is_auto = true;
        }

        // Apply move to layout
        if (src_is_reserve) {
            // Find card index in reserve
            Card c = ParseCleanCard(clean_card_code);
            int r_idx = -1;
            for(int i=0; i<layout.GetReserve().size(); ++i) {
                if (layout.GetReserve()[i] == c) {
                    r_idx = i;
                    break;
                }
            }
            
            if (r_idx != -1) {
                if (dest_is_foundation) layout.ApplyReserveToFoundation(r_idx);
                else if (dest_idx != -1) layout.ApplyReserveToTableau(r_idx, dest_idx);
            }
        } else {
            // Source is Tableau
            if (dest_is_foundation) layout.ApplyTableauToFoundation(src_idx);
            else if (dest_is_reserve) layout.ApplyTableauToReserve(src_idx);
            else if (dest_idx != -1) layout.ApplyTableauToTableau(src_idx, dest_idx);
        }

        string step_str = "Step " + to_string(step++) + ": Move " + card_name + " from " + source_name + " to " + dest_name + on_card;
        if (is_auto) {
            cout << "\033[34m" << step_str << "\033[0m" << endl;
        } else {
            cout << step_str << endl;
        }
    }
}

string CaptureAutoMoves(Node& node) {
    if (!options.auto_play) return "";
    string encoded_moves = "";
    bool moved = true;
    while (moved) {
        // Check challenge
        if (options.challenge_code != "00" && CheckChallenge(&node, options.challenge_code)) {
            break;
        }

        moved = false;
        // Check Reserve
        for (int i = 0; i < node.GetReserve().size(); ++i) {
            if (node.CanAutoPlay(node.GetReserve()[i])) {
                string clean_card = node.GetReserve()[i].ToCleanString();
                string encoded = clean_card + "_R_F";
                encoded_moves += encoded;
                node.ApplyReserveToFoundation(i);
                moved = true;
                break; 
            }
        }
        if (moved) continue;

        // Check Tableau
        for (int i = 0; i < 8; ++i) {
            if (!node.GetTableau(i).empty() && node.CanAutoPlay(node.GetTableau(i).Top())) {
                string clean_card = node.GetTableau(i).Top().ToCleanString();
                string encoded = clean_card + "_" + to_string(i) + "_F";
                encoded_moves += encoded;
                node.ApplyTableauToFoundation(i);
                moved = true;
                break;
            }
        }
    }
    return encoded_moves;
}

#include <queue>
#include <unordered_set>
#include <tuple>
#include <iomanip>

class AStarSolver {
public:
    string Solve(const Node& layout, string challenge_code) {
        if (challenge_code == "00") return "";
        
        cout << "DEBUG: AStarSolver::Solve invoked for Challenge: " << challenge_code << endl;
        
        // 1. Parse Targets
        vector<Card> all_potential_targets = ParseTargets(challenge_code);
        if (all_potential_targets.empty()) {
            cout << "Error: Could not parse targets." << endl;
            return "";
        }
        
        // 2. Setup A*
        Pool pool; 
        // Use hash for closed set to save memory (size_t is 4 or 8 bytes vs string 100+ bytes)
        std::unordered_set<size_t> closed_set;
        std::priority_queue<State, vector<State>, CompareState> open_set;
        
        Node* root = pool.New(layout);
        int h = CalculateHeuristic(root, all_potential_targets);
        
        open_set.push(State(root, 0, h, 0));
        size_t root_hash = std::hash<string>{}(SerializeState(root));
        closed_set.insert(root_hash);
        
        int nodes_expanded = 0;
        int id_counter = 0;

        // Determine target count needed
        int required_count = all_potential_targets.size();
        if (isdigit(challenge_code[1])) {
            required_count = challenge_code[1] - '0';
        }

        while (!open_set.empty()) {
            State current = open_set.top();
            open_set.pop();
            
            Node* node = current.GetNode();

            // 3. Check Goal
            int met_count = 0;
            if (all_potential_targets.size() == 4 && required_count < 4) {
                 for(const auto& t : all_potential_targets) {
                     if (node->GetFoundation(t.suit()).Has(t)) met_count++;
                 }
            } else {
                 met_count = 0;
                 for(const auto& t : all_potential_targets) {
                     if (node->GetFoundation(t.suit()).Has(t)) met_count++;
                 }
                 if (met_count == all_potential_targets.size()) met_count = required_count; 
                 else met_count = 0; 
            }

            if (met_count >= required_count) {
                 cout << "A* Solution Found! Nodes expanded: " << nodes_expanded << endl;
                 cout << "Solution Length: " << node->moves_performed() << endl;
                 
                 string code;
                 {
                     // Reconstruct path
                     ScopedNode temp_node(&pool, pool.New(layout));
                     Node::CompressedMoves::Reader reader(node->moves());
                     for (int i = 0; i < node->moves_performed(); ++i) {
                        auto new_nodes = temp_node->Expand(&pool).ToVector();
                        int move_index = reader.Read(new_nodes.size());
                        auto picked_node = new_nodes[move_index];
                        for (auto* n : new_nodes) if (n != picked_node) pool.Delete(n);
                        temp_node.reset(picked_node);
                        code += temp_node->last_move().Encode();
                     }
                 }
                 return code;
            }
            
            // 4. Expand
            nodes_expanded++;
            if (nodes_expanded % 100000 == 0) cout << "Expanded: " << nodes_expanded << " f=" << current.f() << " g=" << current.GetG() << endl;
            
            auto children = node->Expand(&pool);
            for (Node* child : children) {
                // Optimize: Hash state immediately
                string child_str = SerializeState(child);
                size_t child_hash = std::hash<string>{}(child_str);

                if (closed_set.find(child_hash) == closed_set.end()) {
                    closed_set.insert(child_hash);
                    
                    int child_h = 0;
                    if (all_potential_targets.size() == 4 && required_count < 4) {
                         vector<int> costs;
                         for(const auto& t : all_potential_targets) costs.push_back(GetRecursiveHeuristic(child, t));
                         std::sort(costs.begin(), costs.end());
                         for(int i=0; i<required_count; ++i) child_h += costs[i];
                    } else {
                         child_h = CalculateHeuristic(child, all_potential_targets);
                    }

                    open_set.push(State(child, current.GetG() + 1, child_h, ++id_counter));
                } else {
                    pool.Delete(child);
                }
            }
        }

        cout << "A* Search failed to find a solution." << endl;
        return "";
    }

private:
   class State {
    public:
        State(Node* n, int g_val, int h_val, int id_val) 
            : node_(n), g_(g_val), h_(h_val), id_(id_val) {}

        int f() const { return g_ + h_; }
        int GetG() const { return g_; }
        Node* GetNode() const { return node_; }
        int GetId() const { return id_; }

    private:
        Node* node_;
        int g_;
        int h_;
        int id_; 
    };

    struct CompareState {
        bool operator()(const State& a, const State& b) {
            if (a.f() != b.f()) return a.f() > b.f();
            return a.GetId() > b.GetId(); 
        }
    };

    // Serialize state for Closed Set
    string SerializeState(const Node* node) {
        string s = "";
        // Foundations (only top matters)
        for(int i=0; i<4; ++i) {
            if (node->GetFoundation(i).empty()) s += "00";
            else s += node->GetFoundation(i).Top(i).ToCleanString();
        }
        // Reserve 
        vector<string> reserve_strs;
        const auto& current_reserve = node->GetReserve();
        for(int i=0; i<current_reserve.size(); ++i) {
            reserve_strs.push_back(current_reserve[i].ToCleanString());
        }
        std::sort(reserve_strs.begin(), reserve_strs.end());
        for(const auto& rs : reserve_strs) s += rs;

        // Tableau
        for(int i=0; i<8; ++i) {
            s += "|";
            const auto& t = node->GetTableau(i);
            for(int j=0; j<t.size(); ++j) {
                s += t.card(j).ToCleanString();
            }
        }
        return s;
    }

    // Calculate Depth of a card in the layout
    int GetCardDepth(const Node* node, Card target) {
        // Check Reserve
        const auto& current_reserve = node->GetReserve();
        for(int i=0; i<current_reserve.size(); ++i) {
            if (current_reserve[i] == target) return 0; // Accessible
        }
        
        // Check Tableau
        for(int i=0; i<8; ++i) {
            const auto& t = node->GetTableau(i);
            for(int j=0; j<t.size(); ++j) {
                if (t.card(j) == target) {
                    return t.size() - 1 - j;
                }
            }
        }
        
        if (node->GetFoundation(target.suit()).Has(target)) return -1; // Done

        return 1000;
    }

    int GetRecursiveHeuristic(const Node* node, Card target, int depth_limit = 13) {
        if (depth_limit <= 0) return 0; 
        
        if (node->GetFoundation(target.suit()).Has(target)) return 0;

        int current_depth = GetCardDepth(node, target);
        if (current_depth == -1) return 0; // Already in foundation

        int cost = current_depth;
        
        if (target.rank() > ACE) {
            Card prereq(target.suit(), target.rank() - 1);
            cost += GetRecursiveHeuristic(node, prereq, depth_limit - 1);
        }
        
        return cost;
    }

    int CalculateHeuristic(const Node* node, const vector<Card>& targets) {
        int total_h = 0;
        for(const auto& t : targets) {
            total_h += GetRecursiveHeuristic(node, t);
        }
        return total_h;
    }

    vector<Card> ParseTargets(string code) {
       vector<Card> targets;
       if (code.length() == 2) {
            char rank_char = code[0];
            char type_char = code[1];
            
            int rank = -1;
            if (isdigit(rank_char)) {
                // '1' -> Ace (0), '9' -> R9 (8)
                int val = rank_char - '0';
                if (val >= 1 && val <= 9) rank = val - 1;
            } else {
                char lower_r = tolower(rank_char);
                if (lower_r == 'a') rank = 0; // Just in case 'a' is used for Ace
                else if (lower_r == 't') rank = 9; // Ten
                else if (lower_r == 'j') rank = 10;
                else if (lower_r == 'q') rank = 11;
                else if (lower_r == 'k') rank = 12;
            }

            if (rank != -1) {
                 if (isalpha(type_char)) {
                     int suit = -1;
                     char s = tolower(type_char);
                     if (s == 'c') suit = CLUB;
                     else if (s == 'd') suit = DIAMOND;
                     else if (s == 'h') suit = HEART;
                     else if (s == 's') suit = SPADE;
                     if (suit != -1) targets.emplace_back(suit, rank);
                 }
                 else if (isdigit(type_char)) {
                     for(int s=0; s<4; ++s) targets.emplace_back(s, rank);
                 }
            }
       }
       return targets;
    }
};

string SolveByAStar(const Node& layout) {
    AStarSolver solver;
    return solver.Solve(layout, options.challenge_code);
}

int main(int argc, char** argv) {
  // Hardcoded options for the sample
  options.seed = 2;
  options.beam_size = 2048;
  options.num_beams = 1;
  options.quiet = false;
  options.auto_play = true;
  Node::Initialize();

  // Determine solutions directory
  string solutions_dir = "../Solutions/";
  {
      ifstream check_dir(solutions_dir + "sol_0");
      if (!check_dir.good()) {
          string alt_dir = "Test/freecell/Solutions/";
          ifstream check_alt(alt_dir + "sol_0");
          if (check_alt.good()) {
              solutions_dir = alt_dir;
          }
      }
  }

  // Encoded Deck Configuration
  string encoded_deck = "";
  
  if (argc > 1) {
      encoded_deck = argv[1];
  }

  // Parse Challenge and Moves if present
  size_t first_dollar = encoded_deck.find('$');
  if (first_dollar != string::npos) {
      size_t second_dollar = encoded_deck.find('$', first_dollar + 1);
      if (second_dollar != string::npos) {
          options.challenge_code = encoded_deck.substr(first_dollar + 1, second_dollar - first_dollar - 1);
          string moves_str = encoded_deck.substr(second_dollar + 1);
          try {
              options.move_limit = stoi(moves_str);
          } catch (...) {
              options.move_limit = 0;
          }
          if (options.move_limit > 0) {
              if (options.challenge_code != "00") {
                  options.auto_play = false;
                  cout << "AutoPlay disabled due to Move Limit in Challenge." << endl;
              }
          }
          // Truncate deck string to just the deck part
          encoded_deck = encoded_deck.substr(0, first_dollar);
          
          cout << "Challenge Detected: " << options.challenge_code << endl;
          cout << "Move Limit: " << options.move_limit << endl;
      }
  }

  // Parse Reserve (first 8 chars -> 4 slots)
  vector<Card> reserve_cards;
  for(int i=0; i<4; ++i) {
      string s = encoded_deck.substr(i*2, 2);
      if(s != "00") reserve_cards.push_back(ParseCleanCard(s));
  }

  // Parse Foundation (next 8 chars -> 4 slots: H, C, D, S)
  vector<Card> foundation_tops(4, Card(-1)); // Init with invalid
  int suit_order_parse[] = {HEART, CLUB, DIAMOND, SPADE};
  for(int i=0; i<4; ++i) {
      string s = encoded_deck.substr(8 + i*2, 2);
      if(s != "00") {
          Card c = ParseCleanCard(s);
          foundation_tops[suit_order_parse[i]] = c;
      }
  }

  // Parse Tableau
  vector<vector<Card>> tableaus(8);
  string tableau_part = encoded_deck.substr(16);
  
  const char* markers[] = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii"};
  size_t positions[9];
  size_t current_pos = 0;
  for(int i=0; i<8; ++i) {
      size_t pos = tableau_part.find(markers[i], current_pos);
      positions[i] = pos;
      current_pos = pos + strlen(markers[i]);
  }
  positions[8] = tableau_part.length();

  for(int i=0; i<8; ++i) {
      size_t start = positions[i] + strlen(markers[i]);
      size_t end = positions[i+1];
      string cards_str = tableau_part.substr(start, end - start);
      for(size_t k=0; k<cards_str.length(); k+=2) {
          tableaus[i].push_back(ParseCleanCard(cards_str.substr(k, 2)));
      }
  }

  Node layout;
  layout.LoadState(reserve_cards, foundation_tops, tableaus);
  Node initial_layout = layout;

  // Encode Deck Configuration for checking existing solutions
  string deck_encoded_str = "";

  // Reserve (4 slots)
  const auto& reserve = layout.GetReserve();
  for (int i = 0; i < 4; ++i) {
      if (i < reserve.size()) {
          deck_encoded_str += reserve[i].ToCleanString();
      } else {
          deck_encoded_str += "00";
      }
  }

  // Foundation (4 slots: H, C, D, S)
  int suit_order[] = {HEART, CLUB, DIAMOND, SPADE};
  for (int k = 0; k < 4; ++k) {
      int s = suit_order[k];
      const auto& f = layout.GetFoundation(s);
      if (f.empty()) {
          deck_encoded_str += "00";
      } else {
          deck_encoded_str += f.Top(s).ToCleanString();
      }
  }

  // Tableau
  const char* roman_numerals[] = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii"};
  for (int i = 0; i < 8; ++i) {
      deck_encoded_str += roman_numerals[i];
      const auto& t = layout.GetTableau(i);
      for (int j = 0; j < t.size(); ++j) {
          deck_encoded_str += t.card(j).ToCleanString();
      }
  }
  
  // Capture initial auto moves
  string initial_auto_moves = CaptureAutoMoves(layout);
  // layout is now in the state after initial auto moves

  // Check if solution already exists
  int check_n = 0;
  while (true) {
      string check_filename = solutions_dir + "sol_" + to_string(check_n);
      ifstream f(check_filename);
      if (!f.good()) break;

      string file_deck_config;
      if (getline(f, file_deck_config)) {
          // Remove any potential carriage return
          if (!file_deck_config.empty() && file_deck_config.back() == '\r') {
              file_deck_config.pop_back();
          }
          
          if (file_deck_config == deck_encoded_str) {
              string file_solution;
              if (getline(f, file_solution)) {
                  if (!file_solution.empty() && file_solution.back() == '\r') {
                      file_solution.pop_back();
                  }
                  
                  cout << "Found existing solution in " << check_filename << "\n\n";
                  
                  cout << "Encoded deck configuration\n" << file_deck_config << "\n\n";

                  cout << "Readable deck configuration\n";
                  Node display_layout = initial_layout;
                  display_layout.Show();
                  cout << "\n";

                  // Check if file_solution is missing initial auto moves
                  string full_solution = file_solution;
                  if (file_solution.find(initial_auto_moves) != 0) {
                      // Prepend missing auto moves
                      full_solution = initial_auto_moves + file_solution;
                  }

                  cout << "Encoded solution\n" << full_solution << "\n\n";
                  
                  cout << "Readable solution\n";
                  Node layout_replay = initial_layout;
                  
                  DecodeAndShow(full_solution, layout_replay);
                  return 0;
              }
          }
      }
      check_n++;
  }

  if (!options.quiet) layout.Show();

  // Adjust move limit for initial auto moves
  int initial_moves_count = 0;
  for (char c : initial_auto_moves) {
      if (c == 'F') initial_moves_count++;
  }
  if (options.move_limit > 0) {
      options.move_limit -= initial_moves_count;
      if (options.move_limit < 0) options.move_limit = 0;
      if (!options.quiet) cout << "Adjusted Move Limit (after " << initial_moves_count << " auto moves): " << options.move_limit << endl;
  }

  vector<Move> moves;
  string solution_str;

  if (options.challenge_code == "00") {
      for (int i = 0; i < options.num_beams; ++i)
        beams.emplace_back(
            new Beam(options.seed, options.beam_size, i, options.num_beams));

      if (options.num_beams == 1) {
          solution_str = beams[0]->Solve(layout);
      } else {
          vector<std::unique_ptr<std::thread>> threads;
          for (int i = 0; i < options.num_beams; ++i)
            threads.emplace_back(new std::thread(
                std::bind(&Beam::Solve, beams[i].get(), layout)));
          for (int i = 0; i < options.num_beams; ++i) threads[i]->join();
          // Note: In multi-threaded mode, we'd need to capture the solution from the winning thread.
          // For this sample, we assume single thread.
      }
  } else {
      solution_str = SolveByAStar(layout);
  }

  if (!solution_str.empty()) {
      
      // printf("\n\n--- Readable Solution ---\n"); // Moved to end
      auto solution_moves = DecodeSolution(solution_str);
      
      Node current_layout = layout;
      int step = 1;
      string encoded_solution_string = initial_auto_moves;

      // Helper lambda to print a move
      // We will store the readable output in a buffer and print it AFTER the encoded string
      // stringstream readable_output_buffer; // Removed
      
      auto PrintMove = [&](string card_name, string source, string dest, string on_card, bool is_auto = false, string encoded_step = "") {
          // stringstream ss;
          // string clean_card = StripAnsi(card_name);
          // string clean_on_card = StripAnsi(on_card);
          
          if (!encoded_step.empty()) {
              // Removed pipe separator as per request
              encoded_solution_string += encoded_step;
          }

          // No printing here
      };

      // Initial AutoPlay - Already done and captured in initial_auto_moves
      // ProcessAutoMoves(current_layout); 

      for (const auto& move : solution_moves) {
          // Capture state before move
          string card_name = "Unknown";
          string source = "Unknown";
          string dest = "Unknown";
          string on_card = "";
          string encoded_step = "";
          int dest_size_before = 0;

          if (move.type == kTableauToReserve) {
              Card c = current_layout.GetTableau(move.from).Top();
              card_name = c.ToString();
              source = "Tableau " + to_string(move.from + 1);
              dest = "Reserve";
              // Encode: card_col_R
              encoded_step = c.ToCleanString() + "_" + to_string(move.from) + "_R";

          } else if (move.type == kTableauToTableau) {
              Card c = current_layout.GetTableau(move.from).Top();
              card_name = c.ToString();
              source = "Tableau " + to_string(move.from + 1);
              dest = "Tableau " + to_string(move.to + 1);
              dest_size_before = current_layout.GetTableau(move.to).size();
              if (!current_layout.GetTableau(move.to).empty()) {
                  on_card = string(" (on ") + current_layout.GetTableau(move.to).Top().ToString() + ")";
              } else {
                  on_card = " (empty column)";
              }
              // Encode: card_col_~col~
              encoded_step = c.ToCleanString() + "_" + to_string(move.from) + "_~" + to_string(move.to) + "~";

          } else if (move.type == kTableauToFoundation) {
              Card c = current_layout.GetTableau(move.from).Top();
              card_name = c.ToString();
              source = "Tableau " + to_string(move.from + 1);
              dest = "Foundation";
              // Encode: card_col_F
              encoded_step = c.ToCleanString() + "_" + to_string(move.from) + "_F";

          } else if (move.type == kReserveToTableau) {
              Card c = current_layout.GetReserve()[move.from];
              card_name = c.ToString();
              source = "Reserve";
              dest = "Tableau " + to_string(move.to + 1);
              if (!current_layout.GetTableau(move.to).empty()) {
                  on_card = string(" (on ") + current_layout.GetTableau(move.to).Top().ToString() + ")";
              } else {
                  on_card = " (empty column)";
              }
              // Encode: card_R_~col~
              encoded_step = c.ToCleanString() + "_R_~" + to_string(move.to) + "~";

          } else if (move.type == kReserveToFoundation) {
              Card c = current_layout.GetReserve()[move.from];
              card_name = c.ToString();
              source = "Reserve";
              dest = "Foundation";
              // Encode: card_R_F
              encoded_step = c.ToCleanString() + "_R_F";
          }

          // Apply the move manually (without AutoPlay)
          if (move.type == kTableauToReserve) current_layout.ApplyTableauToReserve(move.from);
          else if (move.type == kTableauToTableau) current_layout.ApplyTableauToTableau(move.from, move.to);
          else if (move.type == kTableauToFoundation) current_layout.ApplyTableauToFoundation(move.from);
          else if (move.type == kReserveToTableau) current_layout.ApplyReserveToTableau(move.from, move.to);
          else if (move.type == kReserveToFoundation) current_layout.ApplyReserveToFoundation(move.from);

          // Check for stack move
          if (move.type == kTableauToTableau) {
              int dest_size_after = current_layout.GetTableau(move.to).size();
              int moved_count = dest_size_after - dest_size_before;
              if (moved_count > 1) {
                  card_name = "stack of " + to_string(moved_count) + " cards (" + card_name + ")";
                  // Update encoded step for stack move: card#count_col_~col~
                  // We need the bottom card of the stack being moved.
                  // The cards moved are the top 'moved_count' cards from the source column (before move).
                  // But we already applied the move.
                  // The cards are now at the top of 'dest' column.
                  // The bottom card of the moved stack is at index: dest_size_after - moved_count.
                  Card bottom_card = current_layout.GetTableau(move.to).card(dest_size_after - moved_count);
                  encoded_step = bottom_card.ToCleanString() + "#" + to_string(moved_count) + "_" + to_string(move.from) + "_~" + to_string(move.to) + "~";
              }
          }

          PrintMove(card_name, source, dest, on_card, false, encoded_step);

          // Check for Auto Moves triggered by this move
          encoded_solution_string += CaptureAutoMoves(current_layout);
          
          // Check if challenge is met
          if (options.challenge_code != "00" && CheckChallenge(&current_layout, options.challenge_code)) {
              break;
          }
      }
      
      cout << "\nEncoded deck configuration\n" << deck_encoded_str << "\n\n";

      cout << "Readable deck configuration\n";
      Node display_layout = initial_layout;
      display_layout.Show();
      cout << "\n";

      cout << "Encoded solution\n" << encoded_solution_string << "\n\n";
      
      // Deck Configuration is already encoded in deck_encoded_str

      // Find next available filename sol_n in solutions_dir
      string filename;
      int n = 0;
      while (true) {
          filename = solutions_dir + "sol_" + to_string(n);
          ifstream f(filename);
          bool exists = f.good();
          f.close();
          if (!exists) break;
          n++;
      }
      
      ofstream outfile(filename);
      if (outfile.is_open()) {
          outfile << deck_encoded_str << endl;
          outfile << encoded_solution_string << endl;
          cout << "Saved encoded solution to " << filename << "\n\n";
      } else {
          cerr << "Error: Could not open file " << filename << " for writing." << endl;
      }

      // Decode and show
      cout << "Readable solution\n";
      Node display_layout_final = initial_layout;
      DecodeAndShow(encoded_solution_string, display_layout_final);

      printf("-------------------------\n");
  }

  cout << "Solver finished successfully." << endl;
  return 0;
}

