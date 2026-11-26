/* Review 2026-11-26: exhaustive Petersen + (10-r) H7 + r H8* orientation check (min-window model).
   Usage: python3 h8.py && gcc -O2 -o pet pet.c && ./pet */
#include <stdio.h>
int cv[12][5],cp[12][5];
int main(){FILE*f=fopen("pet.txt","r");for(int c=0;c<12;c++)for(int i=0;i<5;i++)if(fscanf(f,"%d %d",&cv[c][i],&cp[c][i])!=2)return 1;
 for(int r=0;r<=3;r++){long sols=0;int minbad=99;long subsets=0;
  for(int S=0;S<1024;S++){if(__builtin_popcount(S)!=r)continue;subsets++;
   int ori[10];for(int code=0;code<59049;code++){int x=code;for(int v=0;v<10;v++){ori[v]=x%3;x/=3;}
    int bad=0;for(int c=0;c<12;c++){int h=0;for(int i=0;i<5;i++){int v=cv[c][i];int sp=(cp[c][i]==ori[v]);h+=((S>>v)&1)?!sp:sp;}if(h<2)bad++;}
    if(!bad)sols++; if(bad<minbad)minbad=bad;}}
  printf("r=%d (n=%d): subsets=%ld  zero-bad solutions=%ld  min #bad 5-cycles=%d\n",r,70+r,subsets,sols,minbad);}}
