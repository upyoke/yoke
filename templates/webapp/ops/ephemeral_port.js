// ephemeral_port.js — njs module for convention-based port computation
//
// Computes container port from subdomain using the same SHA-256 hash
// algorithm as the deploy workflow:
//   offset = parseInt(sha256(subdomain).substring(0, 8), 16) % PORT_RANGE
//   port   = PORT_BASE + offset
//
// Template variables (replaced during render):
//   {{port_base}}  — base port for web containers (e.g., 4000)
//   {{port_range}} — modulo range for hash (e.g., 100)
//
// Install: copy to /etc/nginx/njs.d/ephemeral_port.js on the VPS.
// Requires: ngx_http_js_module (njs) loaded in nginx.conf.

var PORT_BASE = {{port_base}};
var PORT_RANGE = {{port_range}};

function computePort(r) {
    var subdomain = r.variables.subdomain;
    if (!subdomain) {
        return String(PORT_BASE);
    }
    var hash = require('crypto').createHash('sha256')
        .update(subdomain)
        .digest('hex');
    var offset = parseInt(hash.substring(0, 8), 16) % PORT_RANGE;
    return String(PORT_BASE + offset);
}

export default { computePort };
