
import os

# Default Configuration
# These can be overridden by arguments in the future
SOURCE_DIRS = ["src/deploy"]  # Target the deploy project for obfuscation
BUILD_DIR = "build_obfuscated"
# Put header in same directory as source files so #include "..." works
OBF_LIB_PATH = os.path.join(BUILD_DIR, "deploy", "obfuscator_full.hpp")

# Valid extensions for C++ files
VALID_EXTENSIONS = [".cpp", ".c", ".h", ".hpp", ".cc", ".cxx"]

# Dynamic Obfuscation Names
import random
import string

def _prob_random_name(prefix="_"):
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=random.randint(8, 16)))

NS_NAME = _prob_random_name("__0N")
CLASS_NAME = _prob_random_name("__0C")
METHOD_NAME = _prob_random_name("__0d")
SBOX_NAME = _prob_random_name("__0S")
MACRO_NAME = _prob_random_name("__0M")
