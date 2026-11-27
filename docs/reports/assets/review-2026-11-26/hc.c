/* Review follow-up 2026-11-27: independent local search (degree-preserving switches) for connected
   {C4,C8}(,C16 if n>=16)-free port gadgets. Usage: ./hc <n_ports> <noPE 0|1> <restarts> <deg...> */
/* Independent local search: graphs with given degree sequence (first np ports), connected,
   no C4 and no C8 (and no C16 if n>=16); optional no port-port edges. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int n,np,nope,deg[32],A[32][32];unsigned long long rs=88172645463325252ULL;
unsigned rnd(){rs^=rs<<13;rs^=rs>>7;rs^=rs<<17;return (unsigned)rs;}
int cnt[40];
void dfs(int s,int u,int d,int vis,int first){ for(int w=0;w<n;w++)if(A[u][w]&&w>s&&!(vis>>w&1)){ if(d+1<=(n>=16?16:8))dfs(s,w,d+1,vis|1<<w,first);} 
  if(d>=3&&A[u][s]&&first<u)cnt[d]++;}
int cost(){memset(cnt,0,sizeof cnt);for(int s=0;s<n;s++)for(int v=s+1;v<n;v++)if(A[s][v])dfs(s,v,2,1<<s|1<<v,v);
  int c=cnt[4]+cnt[8]+(n>=16?cnt[16]:0);
  /* connectivity */ int vis=1,q=1; while(q){int u=__builtin_ctz(q);q&=q-1;for(int w=0;w<n;w++)if(A[u][w]&&!(vis>>w&1)){vis|=1<<w;q|=1<<w;}}
  if(vis!=(1<<n)-1)c+=50; return c;}
int ok_edge(int a,int b){return a!=b&&!A[a][b]&&!(nope&&a<np&&b<np);}
int build(){int st[200],m=0;for(int i=0;i<n;i++)for(int k=0;k<deg[i];k++)st[m++]=i;
 for(int t=0;t<1000;t++){memset(A,0,sizeof A);for(int i=m-1;i>0;i--){int j=rnd()%(i+1);int x=st[i];st[i]=st[j];st[j]=x;}
  int bad=0;for(int i=0;i<m;i+=2){if(!ok_edge(st[i],st[i+1])){bad=1;break;}A[st[i]][st[i+1]]=A[st[i+1]][st[i]]=1;} if(!bad)return 1;}return 0;}
int main(int c,char**v){np=atoi(v[1]);nope=atoi(v[2]);int restarts=atoi(v[3]);n=c-4;for(int i=0;i<n;i++)deg[i]=atoi(v[4+i]);rs+=n*7919+nope;
 int found=0;
 for(int r=0;r<restarts&&!found;r++){ if(!build())continue; int cur=cost();
  for(int it=0;it<4000&&cur>0;it++){ int E[64][2],m=0;for(int a=0;a<n;a++)for(int b=a+1;b<n;b++)if(A[a][b]){E[m][0]=a;E[m][1]=b;m++;}
   int e1=rnd()%m,e2=rnd()%m;if(e1==e2)continue;int a=E[e1][0],b=E[e1][1],x=E[e2][0],y=E[e2][1];if(rnd()&1){int t=x;x=y;y=t;}
   if(a==x||a==y||b==x||b==y)continue; if(!ok_edge(a,x)||!ok_edge(b,y))continue;
   A[a][b]=A[b][a]=A[x][y]=A[y][x]=0;A[a][x]=A[x][a]=A[b][y]=A[y][b]=1;int nc=cost();
   if(nc<=cur||rnd()%100<3)cur=nc;else{A[a][x]=A[x][a]=A[b][y]=A[y][b]=0;A[a][b]=A[b][a]=A[x][y]=A[y][x]=1;}}
  if(cur==0){found=1;printf("FOUND edges:");for(int a=0;a<n;a++)for(int b=a+1;b<n;b++)if(A[a][b])printf(" %d-%d",a,b);printf("\n");}}
 if(!found)printf("none found in %d restarts\n",restarts);}
