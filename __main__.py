#!/usr/bin/env python3
"""
Obfuscator CLI Tool

Run with: python3 -m src.obfuscator_c [options]
"""

import argparse
import sys
import os


def create_parser():
    parser = argparse.ArgumentParser(
        prog='obfuscator_c',
        description='C/C++ Code Obfuscator with VM Protection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m obfuscator_c                     # Default: obfuscate src/deploy
  python3 -m obfuscator_c -s ./myproject      # Custom source directory
  python3 -m obfuscator_c -o ./build          # Custom output directory
  python3 -m obfuscator_c --no-vm             # Disable VM protection
  python3 -m obfuscator_c --list-passes       # Show available passes
  python3 -m obfuscator_c --disable-pass mba  # Disable specific pass
"""
    )
    
    # Source/Output options
    parser.add_argument('-s', '--source-dir', 
                        help='Source directory to obfuscate (default: src/deploy)')
    parser.add_argument('-o', '--output-dir',
                        help='Output directory for obfuscated code (default: build_obfuscated)')
    
    # VM Protection options
    parser.add_argument('--no-vm', action='store_true',
                        help='Disable VM protection pass entirely')
    parser.add_argument('--vm-exclude', nargs='+', metavar='FUNC',
                        help='Functions to EXCLUDE from VM virtualization (all others are virtualized)')
    
    # Pass control
    parser.add_argument('--list-passes', action='store_true',
                        help='List available obfuscation passes and exit')
    parser.add_argument('--disable-pass', action='append', metavar='PASS',
                        dest='disabled_passes', default=[],
                        help='Disable specific pass (can be used multiple times)')
    parser.add_argument('--enable-only', nargs='+', metavar='PASS',
                        help='Enable only specified passes')
    
    # Verbosity
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress all output except errors')
    
    # Other options
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--version', action='version', version='%(prog)s 1.0.0')
    
    return parser


def list_passes():
    """Print available obfuscation passes."""
    passes = {
        'AST Phase (Structural)': [
            ('string-encrypt', 'Encrypt string literals'),
            ('obf-func', 'Wrap function calls with OBF_FUNC'),
            ('icff', 'Indirect Control Flow Flattening'),
            ('junk-inject', 'Inject junk code'),
            ('graph-split', 'Split marked functions into graph paths'),
            ('vm-protect', 'VM bytecode protection'),
        ],
        'Text Phase (AST-based)': [
            ('opaque-pred', 'Opaque predicates on if conditions'),
            ('mba', 'Mixed Boolean Arithmetic'),
            ('insn-subst', 'Instruction substitution'),
            ('bogus-cff', 'Bogus control flow'),
        ],
        'Text Phase (Regex-based)': [
            ('const-encode', 'Constant XOR encoding'),
            ('data-encode', 'Data array encoding'),
        ],
    }
    
    print("\nAvailable Obfuscation Passes:\n")
    for category, pass_list in passes.items():
        print(f"  {category}:")
        for name, desc in pass_list:
            print(f"    {name:16} - {desc}")
        print()


def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if args.list_passes:
        list_passes()
        return 0
    
    # Import here to avoid circular imports
    from . import config
    from .core import Obfuscator
    
    # Apply config overrides
    if args.source_dir:
        config.SOURCE_DIRS = [args.source_dir]
    if args.output_dir:
        config.BUILD_DIR = args.output_dir
        config.OBF_LIB_PATH = os.path.join(args.output_dir, 
                                            os.path.basename(config.SOURCE_DIRS[0]),
                                            "obfuscator_full.hpp")
    
    # Create obfuscator with options
    obf = Obfuscator()
    
    # Pass CLI options to obfuscator
    obf.options = {
        'vm_enabled': not args.no_vm,
        'vm_exclude': args.vm_exclude or [],  # Functions to EXCLUDE from VM
        'disabled_passes': args.disabled_passes or [],
        'enable_only': args.enable_only,
        'verbose': args.verbose,
        'quiet': args.quiet,
        'dry_run': args.dry_run,
    }
    
    # Run
    try:
        obf.run()
        return 0
    except Exception as e:
        if args.verbose:
            import traceback
            traceback.print_exc()
        else:
            print(f"[!] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
