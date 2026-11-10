#!/usr/bin/env python3
"""
Convert MicroPython 1.13-era C modules (libngu, mpy-qr) to the C API used by
current MicroPython (1.2x):

  - STATIC                      -> static
  - old struct-style type defs  -> MP_DEFINE_CONST_OBJ_TYPE(...)
  - MP_REGISTER_MODULE(a, b, 1) -> MP_REGISTER_MODULE(a, b)
  - m_new_obj_var(T, char, n)   -> m_new_obj_var(T, state, char, n)
  - extmod/crypto-algorithms    -> lib/crypto-algorithms
  - "#if MICROPY_SSL_MBEDTLS"   -> "#if NGU_USE_MBEDTLS"  (port uses cifra only)

Usage: modernize_c.py file.c [file.c ...]   (edits in place)
"""
import re, sys

TYPE_RE = re.compile(
    r'(?P<pre>(?:STATIC |static )?)const mp_obj_type_t (?P<name>\w+) = \{\s*'
    r'\{ *&mp_type_type *\},?\s*(?P<body>.*?)\};',
    re.S)

FIELD_RE = re.compile(r'\.(\w+)\s*=\s*([^,\n]+?)\s*,?\s*(?=\n|$)')


def convert_type(m):
    pre = 'static ' if m.group('pre').strip() else ''
    name = m.group('name')
    body = m.group('body')
    fields = []
    qname = None
    for fm in FIELD_RE.finditer(body):
        key, val = fm.group(1), fm.group(2).strip()
        val = re.sub(r'^\((?:void|mp_obj_dict_t) *\*\)', '', val).strip()
        if key == 'name':
            qname = val
            continue
        if key == 'buffer_p':
            # old: .buffer_p = { .get_buffer = fn }
            inner = re.search(r'get_buffer\s*=\s*(\w+)', val)
            key, val = 'buffer', inner.group(1) if inner else val
        if key == 'getiter':
            key = 'iter'
        fields.append((key, val))
    assert qname, name
    flags = 'MP_TYPE_FLAG_NONE'
    if any(k == 'iter' for k, _ in fields) and any(k == 'iternext' for k, _ in fields):
        # old style "getiter + iternext" pair
        fields = [(k, v) for k, v in fields if k != 'iter']
        flags = 'MP_TYPE_FLAG_ITER_IS_ITERNEXT'
        fields = [('iter', v) if k == 'iternext' else (k, v) for k, v in fields]
    args = ''.join(',\n    %s, %s' % kv for kv in fields)
    return '%sMP_DEFINE_CONST_OBJ_TYPE(\n    %s,\n    %s,\n    %s%s\n    );' % (
        pre, name, qname, flags, args)


def fix(src):
    src = TYPE_RE.sub(convert_type, src)
    src = re.sub(r'\bSTATIC\b', 'static', src)
    src = re.sub(r'MP_REGISTER_MODULE\(([^,]+),\s*([^,\)]+),\s*[^\)]+\)',
                 r'MP_REGISTER_MODULE(\1, \2)', src)
    src = re.sub(r'm_new_obj_var\((\w+),\s*char,', r'm_new_obj_var(\1, state, char,', src)
    src = src.replace('extmod/crypto-algorithms/', 'lib/crypto-algorithms/')
    src = re.sub(r'mp_obj_new_str_from_vstr\(\s*&mp_type_bytes\s*,\s*', 'mp_obj_new_bytes_from_vstr(', src)
    src = re.sub(r'mp_obj_new_str_from_vstr\(\s*&mp_type_str\s*,\s*', 'mp_obj_new_str_from_vstr(', src)
    src = re.sub(r'm_new_obj_with_finaliser\((\w+)\)',
                 r'((\1 *)m_malloc_with_finaliser(sizeof(\1)))', src)
    src = re.sub(r'mp_obj_module_get_globals\((\w+)\)',
                 r'(((mp_obj_module_t *)MP_OBJ_TO_PTR(\1))->globals)', src)
    src = re.sub(r'#if\s+MICROPY_SSL_MBEDTLS\b', '#if NGU_USE_MBEDTLS', src)
    src = re.sub(r'#ifdef\s+MICROPY_SSL_MBEDTLS\b', '#if NGU_USE_MBEDTLS', src)
    src = re.sub(r'#if\s+!\s*MICROPY_SSL_MBEDTLS\b', '#if !NGU_USE_MBEDTLS', src)
    src = re.sub(r'#ifndef\s+MICROPY_SSL_MBEDTLS\b', '#if !NGU_USE_MBEDTLS', src)
    return src


if __name__ == '__main__':
    for fn in sys.argv[1:]:
        old = open(fn).read()
        new = fix(old)
        if new != old:
            open(fn, 'w').write(new)
            print('updated', fn)
