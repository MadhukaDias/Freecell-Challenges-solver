#include <iostream>

using namespace std;

int main() {
    string Freecell[4];
    char Foundation[4];
    char Characters[4] = {'h', 'c', 'd', 's'};
    string Tableau[8];

    Freecell[0] = "00";
    Freecell[1] = "6d";
    Freecell[2] = "8s";
    Freecell[3] = "00";

    Foundation[0] = '1';
    Foundation[1] = '1';
    Foundation[2] = '3';
    Foundation[3] = '2';

    Tableau[0] = "4c_4d_ts_7h_7c_js";
    Tableau[1] = "td_kc_9d_9c_jd_8d_7s_6h_5c";
    Tableau[2] = "5d_ks_9s_qh_2c_7d";
    Tableau[3] = "00_00_00_00_00_00_00_00";
    Tableau[4] = "8h_jc_kh_2h_4s_3h";
    Tableau[5] = "kd_qc_jh_tc_9h_8c";
    Tableau[6] = "3c_3s_6s_qs_6c_5s";
    Tableau[7] = "qd_5h_4h_th_00";

    for (int i = 0; i < 4; i++) {
        cout<<Freecell[i];
    }
    for (int i = 0; i < 4; i++) {
        cout<<Foundation[i]<<Characters[i];
    }
    for (int i = 0; i < 8; i++) {
        if (i == 0) {
            cout<<"i";
        } else if (i == 1) {
            cout<<"ii";
        } else if (i == 2) {
            cout<<"iii";
        } else if (i == 3) {
            cout<<"iv";
        } else if (i == 4) {
            cout<<"v";
        } else if (i == 5) {
            cout<<"vi";
        } else if (i == 6) {
            cout<<"vii";
        } else if (i == 7) {
            cout<<"viii";
        }
        for (int j = 0; j < Tableau[i].length(); j++) {
            if (Tableau[i][j] == '_' or Tableau[i][j] == '0') {
                continue;
            } else {
                cout<<Tableau[i][j];
            }
        }
    }
}