#!/usr/bin/env python3
"""Offline JavaScriptCore logic checks. Complements, never replaces, Chrome tests."""
import ctypes as C
import ctypes.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    library = C.util.find_library('javascriptcoregtk-4.1') or C.util.find_library('javascriptcoregtk-6.0')
    if not library:
        raise SystemExit('JavaScriptCore is not installed; use scripts/browser_test.py for browser checks.')
    lib = C.CDLL(library)
    declarations = [
        ('JSGlobalContextCreate', [C.c_void_p], C.c_void_p),
        ('JSStringCreateWithUTF8CString', [C.c_char_p], C.c_void_p),
        ('JSCheckScriptSyntax', [C.c_void_p,C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_void_p)], C.c_bool),
        ('JSEvaluateScript', [C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_void_p)], C.c_void_p),
        ('JSValueToStringCopy', [C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)], C.c_void_p),
        ('JSStringGetMaximumUTF8CStringSize', [C.c_void_p], C.c_size_t),
        ('JSStringGetUTF8CString', [C.c_void_p,C.c_char_p,C.c_size_t], C.c_size_t),
        ('JSStringRelease', [C.c_void_p], None), ('JSGlobalContextRelease', [C.c_void_p], None)]
    for name, args, result in declarations:
        method = getattr(lib, name)
        method.argtypes, method.restype = args, result
    context = lib.JSGlobalContextCreate(None)

    def evaluate(source):
        script = lib.JSStringCreateWithUTF8CString(source.encode())
        error = C.c_void_p()
        lib.JSEvaluateScript(context, script, None, None, 1, C.byref(error))
        lib.JSStringRelease(script)
        if error.value:
            value = lib.JSValueToStringCopy(context, error, None)
            size = lib.JSStringGetMaximumUTF8CStringSize(value)
            buffer = C.create_string_buffer(size)
            lib.JSStringGetUTF8CString(value, buffer, size)
            lib.JSStringRelease(value)
            raise AssertionError(buffer.value.decode())
    try:
        for path in (ROOT / 'reader/web').glob('*.js'):
            script = lib.JSStringCreateWithUTF8CString(path.read_bytes())
            error = C.c_void_p()
            valid = lib.JSCheckScriptSyntax(context, script, None, 1, C.byref(error))
            lib.JSStringRelease(script)
            if not valid:
                raise AssertionError(f'JavaScript syntax error in {path.name}')
        from reader.demo import demo
        with TemporaryDirectory() as tmp:
            demo(tmp, public=True)
            papers = json.loads((Path(tmp) / 'data/2026-10-09.json').read_text())['papers']
        fixture = json.loads((ROOT / 'tests/fixtures/browser-profile.json').read_text())
        evaluate('''globalThis.location={pathname:'/reader/'};globalThis.structuredClone=x=>JSON.parse(JSON.stringify(x));
const elements={};globalThis.document={getElementById:id=>(elements[id] ||= {value:'',textContent:'',events:{},addEventListener(type,callback){this.events[type]=callback;}})};
const storage={};globalThis.localStorage={getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]};
globalThis.fetch=()=>{throw new Error('Unexpected network request for cached private profile');};
const fixture=''' + json.dumps(fixture) + ''';
fixture._reader_cache.updated_at=new Date().toISOString();
localStorage.setItem('arxiv-reader-profile-v1:/reader/',JSON.stringify(fixture));''')
        evaluate((ROOT / 'reader/web/profile.js').read_text())
        evaluate('ReaderProfile.init(["hep-ph","hep-th"],()=>{});const papers=' + json.dumps(papers) + ';')
        evaluate('''
let applied=papers.map(ReaderProfile.apply);
if(applied.map(p=>p.citation.status).join(',')!=='confirmed,provisional,checked,unavailable')throw new Error('Citation states wrong');
if(applied[0].authors[0].match!=='provisional')throw new Error('arXiv author name match failed');
if(applied[0].citation.matches.length!==2)throw new Error('Exact matched publications missing');
elements['profile-clear'].events.click();
if(ReaderProfile.apply(papers[0]).citation.matches.length)throw new Error('Matches survived clearing');
if(Object.keys(storage).length)throw new Error('Settings survived clearing');
elements['profile-followed'].value='Chen | 999';elements['profile-form'].events.submit({preventDefault(){}});
if(ReaderProfile.apply(papers[0]).authors[0].match!=='provisional')throw new Error('Name-only matching failed');
const surnamePaper={...papers[0],public_data:undefined,authors:[{name:'M. Chen'},{name:'Chen, Mira'},{name:'Cheng'},{name:'Chen Li'}]};
if(ReaderProfile.apply(surnamePaper).authors.map(a=>!!a.followed).join(',')!=='true,true,false,false')throw new Error('Surname matching must use arXiv authors with whole-name boundaries');
if(ReaderProfile.apply(papers[0]).citation.status!=='unconfigured')throw new Error('Missing configuration treated as a negative match');
''')
        print('PASS: JavaScript syntax and private-profile logic; no network requests')
    finally:
        lib.JSGlobalContextRelease(context)


if __name__ == '__main__':
    main()
