"""Azioni delegate (data-jt-*) al posto dei gestori inline, e sanitizzatore a lista bianca."""

import glob
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import server

ROOT = Path(server.__file__).resolve().parent
NODE = shutil.which("node")

ACTION_ATTR = re.compile(r"""data-jt-(click|change|input|keydown)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def source_files():
    return sorted(glob.glob(str(ROOT / "frontend" / "js" / "*.js")) + glob.glob(str(ROOT / "frontend" / "html" / "*.html")))


def normalize_template_value(v):
    """Sostituisce le interpolazioni ${...} dei template JS con letterali, come avverrebbe a runtime."""
    v = re.sub(r"\$\{jsArg\([^{}]*\)\}", '"X"', v)
    prev = None
    while prev != v:
        prev = v
        v = re.sub(r"\$\{[^{}]*\}", "0", v)
    return v.replace("&quot;", '"').replace("&#39;", "'")


def run_node(js, payload):
    res = subprocess.run(  # noqa: S603
        [NODE, "-e", js, json.dumps(payload)], capture_output=True, text=True, check=True, cwd=ROOT,
    )
    return json.loads(res.stdout.strip().splitlines()[-1])


LOAD_ACTIONS = r"""
const fs=require('fs'),vm=require('vm');
const listeners={};
const sb={console:{error(){sb.__errors.push([].slice.call(arguments).join(' '));}},__errors:[],__calls:[]};
sb.window=sb;
sb.document={addEventListener(t,f){listeners[t]=f;}};
vm.createContext(sb);
vm.runInContext(fs.readFileSync('frontend/js/ui_actions.js','utf8'),sb);
function node(attrs,parent,extra){return Object.assign({nodeType:1,parentElement:parent||null,
  hasAttribute:k=>k in attrs,getAttribute:k=>attrs[k]},extra||{});}
"""


@unittest.skipUnless(NODE, "node non disponibile")
class TestGrammatica(unittest.TestCase):
    def parse_all(self, values):
        js = LOAD_ACTIONS + "const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(x=>sb.jtParseActions(x)!==null)));"
        return run_node(js, values)

    def test_valori_validi(self):
        validi = [
            "switchTab('dashboard')",
            "switchTab('features');",
            "closeJtMenus(); openLoginScreen(true)",
            'openUserModal("a\\"b@x.it")',
            "openGeminiInspectorModal('ENGINE', \"p\", \"e\", \"eu\")",
            "onPeriodDaysChanged(this.value)",
            "toggleChartsSection(this.checked)",
            "event.stopPropagation(); openUserModal(\"x\")",
            "event.preventDefault(); switchTab('dashboard')",
            "renderCurrentTab()",
            "onBackdrop('closeProjectModal')",
            'openUserModal("a\\b\\fb")',
            "applyBulkSyncAction('x', 1, -2.5, null, false)",
        ]
        self.assertTrue(all(self.parse_all(validi)))

    def test_valori_rifiutati(self):
        vietati = [
            "alert(1)",
            "switchTab('x'); alert(1)",
            "window.switchTab('x')",
            "switchTab(document.cookie)",
            "switchTab('x') // y",
            "switchTab(`x`)",
            "a.b()",
            "event.target.remove()",
            "event.stopPropagation(1)",
            "switchTab('x'),alert(1)",
            "",
            "switchTab('x'",
            "switchTab(x)",
            "switchTab('x')alert(1)",
            "fetch('/x')",
            "eval('1')",
            "switchTab('\\x41')",
            "switchTab(this.parentNode)",
        ]
        self.assertEqual(self.parse_all(vietati), [False] * len(vietati))


@unittest.skipUnless(NODE, "node non disponibile")
class TestDispatcher(unittest.TestCase):
    def scenario(self, body):
        js = LOAD_ACTIONS + body
        return run_node(js, None)

    def test_bubbling_e_stoppropagation(self):
        out = self.scenario(r"""
sb.switchTab=n=>sb.__calls.push('tab:'+n); sb.openUserModal=n=>sb.__calls.push('user:'+n);
const parent=node({'data-jt-click':"switchTab('p')"});
const child=node({'data-jt-click':"openUserModal('c')"},parent);
listeners.click({target:child,cancelBubble:false});
const stopper=node({'data-jt-click':"event.stopPropagation(); openUserModal('s')"},parent);
const ev={target:stopper,cancelBubble:false,stopPropagation(){this.cancelBubble=true;}};
listeners.click(ev);
console.log(JSON.stringify(sb.__calls));""")
        self.assertEqual(out, ["user:c", "tab:p", "user:s"])

    def test_this_value_e_checked(self):
        out = self.scenario(r"""
sb.onPeriodDaysChanged=v=>sb.__calls.push('d:'+v); sb.toggleChartsSection=v=>sb.__calls.push('c:'+v);
listeners.change({target:node({'data-jt-change':'onPeriodDaysChanged(this.value)'},null,{value:'30'})});
listeners.change({target:node({'data-jt-change':'toggleChartsSection(this.checked)'},null,{checked:true})});
console.log(JSON.stringify(sb.__calls));""")
        self.assertEqual(out, ["d:30", "c:true"])

    def test_azione_non_consentita_non_viene_eseguita(self):
        out = self.scenario(r"""
sb.alert=()=>sb.__calls.push('ALERT'); sb.switchTab=n=>sb.__calls.push('tab:'+n);
listeners.click({target:node({'data-jt-click':"switchTab('a'); alert(1)"})});
listeners.click({target:node({'data-jt-click':"alert(1)"})});
console.log(JSON.stringify({calls:sb.__calls,errors:sb.__errors.length}));""")
        self.assertEqual(out, {"calls": [], "errors": 2})

    def test_nodo_staccato_dall_azione_non_interrompe_gli_antenati(self):
        out = self.scenario(r"""
sb.switchTab=n=>sb.__calls.push('tab:'+n);
const parent=node({'data-jt-click':"switchTab('p')"});
const child=node({'data-jt-click':"renderCurrentTab()"},parent);
sb.renderCurrentTab=()=>{child.parentElement=null;sb.__calls.push('render');};
listeners.click({target:child,cancelBubble:false});
console.log(JSON.stringify(sb.__calls));""")
        self.assertEqual(out, ["render", "tab:p"])

    def test_azioni_di_supporto(self):
        out = self.scenario(r"""
sb.closeProjectModal=()=>sb.__calls.push('closed'); sb.switchTab=n=>sb.__calls.push('tab:'+n);
const backdrop=node({'data-jt-click':"onBackdrop('closeProjectModal')"});
listeners.click({target:backdrop});                       // clic sullo sfondo
listeners.click({target:node({},backdrop)});              // clic sul contenuto
const tab=node({'data-jt-keydown':"switchTabOnKey('daily')"});
let prevented=0;
listeners.keydown({target:tab,key:'Enter',preventDefault(){prevented++;}});
listeners.keydown({target:tab,key:'a',preventDefault(){prevented++;}});
const classes=new Set();
sb.document.getElementById=id=>id==='x'?{classList:{add:c=>classes.add(c),toggle:c=>classes.has(c)?classes.delete(c):classes.add(c)}}:null;
sb.hideElementById('x'); const hidden1=classes.has('hidden'); sb.toggleHiddenById('x'); const hidden2=classes.has('hidden');
sb.onBackdrop('alert');
console.log(JSON.stringify({calls:sb.__calls,prevented,hidden1,hidden2}));""")
        self.assertEqual(out, {"calls": ["closed", "tab:daily"], "prevented": 1, "hidden1": True, "hidden2": False})


class TestNessunGestoreInline(unittest.TestCase):
    INLINE = re.compile(r"""\bon[a-z]{3,}\s*=\s*["']""")

    def test_zero_gestori_inline_nel_codice(self):
        residui = []
        for f in source_files() + [str(ROOT / "index.html")]:
            for n, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
                if self.INLINE.search(line):
                    residui.append(f"{Path(f).name}:{n}: {line.strip()[:90]}")
        self.assertEqual(residui, [])

    @unittest.skipUnless(NODE, "node non disponibile")
    def test_ogni_valore_data_jt_passa_il_parser_e_usa_funzioni_definite(self):
        valori, defined_src = [], ""
        for f in source_files():
            txt = Path(f).read_text(encoding="utf-8")
            if f.endswith(".js"):
                defined_src += txt
            for m in ACTION_ATTR.finditer(txt):
                valori.append(normalize_template_value(m.group(2) if m.group(2) is not None else m.group(3)))
        self.assertGreaterEqual(len(valori), 200)
        js = LOAD_ACTIONS + "const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(x=>{const p=sb.jtParseActions(x);return p?p.map(s=>s.callee):null;})));"
        parsed = run_node(js, valori)
        rifiutati = [v for v, p in zip(valori, parsed, strict=True) if p is None]
        self.assertEqual(rifiutati, [])
        usate = {c for p in parsed for c in p if "." not in c}
        mancanti = [n for n in sorted(usate) if not re.search(rf"function\s+{n}\b|window\.{n}\s*=", defined_src)]
        self.assertEqual(mancanti, [])

    def test_registro_senza_voci_inutili(self):
        txt = read("frontend/js/ui_actions.js")
        elenco = set(re.findall(r"'([A-Za-z]\w+)'", txt[txt.index("JT_ALLOWED_ACTIONS = new Set(["):txt.index("const JT_EVENT_CALLS")]))
        usate = set()
        for f in source_files():
            for m in ACTION_ATTR.finditer(Path(f).read_text(encoding="utf-8")):
                v = m.group(2) if m.group(2) is not None else m.group(3)
                usate |= set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", re.sub(r"\$\{[^{}]*\}", "0", v)))
        self.assertEqual(sorted(usate - elenco), [], "funzioni usate ma non in elenco")
        self.assertEqual(sorted(elenco - usate), [], "voci in elenco mai usate")

    def test_ui_actions_e_assemblato_in_index(self):
        self.assertIn("frontend/js/ui_actions.js", server.FRONTEND_JS_MODULES)
        self.assertIn("jtDispatchAction", read("index.html"))


FAKE_DOM = r"""
const fs=require('fs'),vm=require('vm');
const src=fs.readFileSync('frontend/js/core_and_auth.js','utf8');
const a=src.indexOf('const SANITIZE_ALLOWED_TAGS'), b=src.indexOf('function setSafeHtml');
const code=src.slice(a,b);
const sb={};vm.createContext(sb);vm.runInContext(code+';this.sanitizeFragment=sanitizeFragment;',sb);
function el(tag,attrs){const o={localName:tag,removed:false,attributes:Object.entries(attrs).map(([name,value])=>({name,value})),
  remove(){o.removed=true;},getAttribute(n){const x=o.attributes.find(y=>y.name===n);return x?x.value:null;},
  setAttribute(n,v){const x=o.attributes.find(y=>y.name===n);if(x)x.value=v;else o.attributes.push({name:n,value:v});},
  removeAttribute(n){o.attributes=o.attributes.filter(y=>y.name!==n);}};return o;}
function run(list){sb.sanitizeFragment({querySelectorAll:()=>list});}
"""


@unittest.skipUnless(NODE, "node non disponibile")
class TestSanitizzatoreListaBianca(unittest.TestCase):
    def scenario(self, body):
        return run_node(FAKE_DOM + body, None)

    def test_tag_non_in_elenco_vengono_tolti(self):
        out = self.scenario(r"""
const tags=['script','iframe','object','embed','style','link','meta','base','template','form','math','video','div','svg','path','use','TABLE'];
const nodes=tags.map(t=>el(t,{}));run(nodes);
console.log(JSON.stringify(nodes.filter(n=>n.removed).map(n=>n.localName)));""")
        self.assertEqual(out, ["script", "iframe", "object", "embed", "style", "link", "meta", "base", "template", "form", "math", "video"])

    def test_nessun_gestore_on_sopravvive(self):
        out = self.scenario(r"""
const n=el('div',{inert:'',onclick:'alert(1)',onchange:'x()',oninput:'x()',onerror:'x()',onmouseover:'x()',OnLoad:'x()',class:'a','data-jt-click':"switchTab('a')",'aria-label':'x'});
run([n]);console.log(JSON.stringify(n.attributes.map(a=>a.name)));""")
        self.assertEqual(out, ["inert", "class", "data-jt-click", "aria-label"])

    def test_attributi_non_in_elenco_e_url_pericolosi(self):
        out = self.scenario(r"""
const a1=el('a',{href:'javascript:alert(1)',formaction:'x',srcdoc:'x',class:'k'});
const a2=el('a',{href:' jav\tascript:alert(1)'});
const a3=el('a',{href:'https://example.com',target:'_blank'});
const a4=el('a',{href:'#frag'});const a5=el('a',{href:'data:text/html,x'});
const u1=el('use',{href:'#ico-check'});const u2=el('use',{href:'https://evil/x.svg#a'});
const i1=el('img',{src:'data:image/png;base64,AAAA'});const i2=el('img',{src:'data:image/svg+xml;base64,AAAA'});
const s1=el('div',{style:'color:red'});const s2=el('div',{style:'background:url(https://evil/x)'});
run([a1,a2,a3,a4,a5,u1,u2,i1,i2,s1,s2]);
const names=n=>n.attributes.map(a=>a.name);
console.log(JSON.stringify({a1:names(a1),a2:names(a2),a3:a3.getAttribute('rel'),a4:names(a4),a5:names(a5),u1:names(u1),u2:names(u2),i1:names(i1),i2:names(i2),s1:names(s1),s2:names(s2)}));""")
        self.assertEqual(out, {
            "a1": ["class"], "a2": [], "a3": "noopener noreferrer", "a4": ["href"], "a5": [],
            "u1": ["href"], "u2": [], "i1": ["src"], "i2": [], "s1": ["style"], "s2": [],
        })

    def test_elenco_attributi_senza_gestori_e_azioni(self):
        src = read("frontend/js/core_and_auth.js")
        blocco = src[src.index("const SANITIZE_ALLOWED_ATTRS"):src.index("const SANITIZE_URL_ATTRS")]
        attrs = set(re.findall(r"'([\w:-]+)'", blocco))
        self.assertFalse({a for a in attrs if a.startswith("on")})
        self.assertFalse(attrs & {"action", "formaction", "srcdoc", "srcset", "background", "poster"})


if __name__ == "__main__":
    unittest.main()
