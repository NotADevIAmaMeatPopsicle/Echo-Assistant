#pragma once
namespace TouchTargets {
struct Rect {
    int x,y,w,h;
    bool contains(int px,int py) const { return px>=x && py>=y && px<x+w && py<y+h; }
};
// Navigation retains the accepted generous hit boxes around the smaller icons.
constexpr Rect navHome{75,333,94,42},navTalk{177,333,112,42},navMusic{297,333,94,42};
constexpr Rect homeBose{90,137,137,99},homeThermostat{239,137,137,99};
constexpr Rect homeLights{95,243,276,42},homeWeather{80,290,96,36},homeTimers{185,290,96,36},homeSettings{290,290,96,36};
constexpr Rect roomLights[4]={{90,145,137,73},{239,145,137,73},{90,229,137,73},{239,229,137,73}};
constexpr Rect microphone{99,153,268,42},brightnessDown{126,235,74,42},brightnessUp{266,235,74,42};
constexpr Rect musicPrevious{108,282,70,42},musicToggle{186,282,94,42},musicNext{288,282,70,42};
}
