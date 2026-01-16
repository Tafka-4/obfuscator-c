
import os
import random
from . import config

# Generate a random S-Box (256 bytes)
SBOX = list(range(256))
random.shuffle(SBOX)
SBOX_STR = ", ".join([f"0x{x:02X}" for x in SBOX])


def create_obfuscator_header():
    # randomized SBOX values
    sbox_vals = list(range(256))
    random.shuffle(sbox_vals)
    sbox_str = ", ".join([f"0x{x:02X}" for x in sbox_vals])
    
    # Internal polymorphic junk logic
    # We use Seed to modify the math
    
    header_content = f"""#pragma once
#include <cstddef>
#include <cstdlib>
#include <type_traits>
#include <utility>
#include <cstdint>
#include <array>

#if defined(__APPLE__) || defined(__linux__)
#include <sys/ptrace.h>
#include <sys/types.h>
#include <unistd.h>
#endif

namespace {config.NS_NAME} {{

    // Global S-Box
    static volatile int {config.SBOX_NAME}[256] = {{ {sbox_str} }};

    template <std::size_t N, int Seed>
    class {config.CLASS_NAME} {{
    private:
        char data[N];
        char _k;

    public:
        constexpr {config.CLASS_NAME}(const char* str, unsigned char k) : data{{}}, _k((char)k) {{
            for (std::size_t i = 0; i < N - 1; ++i) {{
                char c = str[i];
                c ^= k;
                // Mild compile-time scrambling if possible, but keep it simple to ensure runtime decrypt works match
                // Actually, let's keep it simple XOR at compile time for now to avoid complexity bugs
                data[i] = c;
            }}
            data[N - 1] = '\\0';
        }}

        const char* {config.METHOD_NAME}() const {{
            // Polymorphic Junk
            volatile unsigned int junk = Seed;
            for(int i=0; i < (Seed % 5) + 2; ++i) {{
                 junk = (junk * 1664525 + 1013904223);
            }}
            
            static char buffer[N];
            // Copy data to static buffer first
            for(std::size_t i=0; i<N; ++i) buffer[i] = data[i];

            for (std::size_t i = 0; i < N - 1; ++i) {{
                buffer[i] ^= _k;
                
                // Junk ops depending on junk state
                if ((junk + i) % 13 == 0) {{
                     volatile int z = buffer[i]; 
                     z = z * 2;
                }}
            }}
            return buffer;
        }}
    }};
    
    namespace security {{
        inline void enforce_anti_debug() {{
            #if defined(__APPLE__)
              ptrace(PT_TRACE_ME, 0, 0, 0);
            #endif
        }}
    }}
}}


// Helper macro
#define {config.MACRO_NAME}(str, key_val, seed_val) ([]() {{ \\
    constexpr std::size_t size = sizeof(str); \\
    constexpr unsigned char k = (unsigned char)key_val; \\
    constexpr int seed = (seed_val); \\
    constexpr {config.NS_NAME}::{config.CLASS_NAME}<size, seed> encrypted(str, k); \\
    return encrypted.{config.METHOD_NAME}(); \\
}})()



// Call Obfuscation
#define OBF_FUNC(f) f

// --- Bogus Control Flow Macros ---
#define OBF_BOGUS_FLOW_LABYRINTH \\
    {{ volatile int _x = 0; if (_x) goto _bogus_lab_1; _x++; if(_x > 10) goto _bogus_lab_2; }} \\
    _bogus_lab_1: {{ volatile int _y = 1; }} \\
    _bogus_lab_2:

#define OBF_BOGUS_FLOW_GRID \\
    if (0) {{ \\
        _grid_start: goto _grid_end; \\
        _grid_mid: goto _grid_start; \\
    }} \\
    _grid_end:

#define OBF_BOGUS_FLOW_SCRAMBLE \\
   {{ volatile int _z = 99; while(_z > 100) {{ _z--; }} }}

// Helpers for ICFF
#define NEXT_STATE(s) ((s * 1664525 + 1013904223) & 0xFFFFFFFF)
"""
    
    os.makedirs(os.path.dirname(config.OBF_LIB_PATH), exist_ok=True)
    with open(config.OBF_LIB_PATH, "w") as f:
        f.write(header_content)

