#include <initializer_list>
#include <assert.h>
#include <math.h>
#include "../src/polargraph_math.h"
static int leaves=0;
void split(const float *a,const float *b,int depth=0) {
  float error=0;
  assert(polargraphLineDeviation(0,644.525,0,a,b,error));
  if(error>.025f || hypotf(b[0]-a[0],b[1]-a[1])>5) {
    assert(depth<16);
    float mid[2]={(a[0]+b[0])*.5f,(a[1]+b[1])*.5f};
    split(a,mid,depth+1);split(mid,b,depth+1);
  } else {
    ++leaves;
    const float la=hypotf(a[0],a[1]),lb=hypotf(b[0],b[1]);
    const float ra=hypotf(a[0]-644.525f,a[1]),rb=hypotf(b[0]-644.525f,b[1]);
    // Dense independent samples verify error between subdivision sample sites.
    for(int i=1;i<100;++i) {
      float t=i/100.f,x,y;
      assert(polargraphPosition(0,644.525,0,la+(lb-la)*t,ra+(rb-ra)*t,x,y));
      assert(hypotf(x-a[0]-(b[0]-a[0])*t,y-a[1]-(b[1]-a[1])*t)<.027f);
    }
  }
}
int main() {
  for(float depth: {45.f,100.f,400.f,1000.f}) {
    float a[2]={20,-depth},b[2]={624,-depth-10};split(a,b);
    float c[2]={322,-depth},d[2]={322,-depth-300};split(c,d);
  }
  assert(leaves>100);
  float a[2]={300,-400},b[2]={300.04f,-400};
  const long l=polargraphSteps(b[0],b[1],0,0,80)-polargraphSteps(a[0],a[1],0,0,80);
  assert(l>0 && l<6); // Must remain executable under ESP32's one-step minimum.
}
