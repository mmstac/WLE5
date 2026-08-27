// TFTespi config for Waveshare dual round LCD board


#define USER_SETUP_ID 30

// See SetupX_Template.h for all options available

#define GC9A01_DRIVER

// #define TFT_eSPI_ENABLE_DMA
#define TFT_WIDTH 240
#define TFT_HEIGHT 240

#define CGRAM_OFFSET      // Library will add offsets required

// Shared SPI Bus Pins
#define TFT_MOSI 42
#define TFT_MISO -1   
#define TFT_SCLK 41
#define TFT_DC   45

// --- NEW FIX: Comment these out so we can manually manage dual screens ---
// #define TFT_CS   -1  
// #define TFT_RST  -1
// #define TFT_BL   -1  

#define TFT_BACKLIGHT_ON HIGH

// Important for Waveshare board
#define USE_HSPI_PORT

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

#define SPI_FREQUENCY 80000000 // Bumped up from 40MHz
