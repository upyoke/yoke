// Compute a deterministic local preview port from the requested subdomain.
// The deployer must use the same SHA-256 rule and configured range.

var PORT_BASE = 9000;
var PORT_RANGE = 100;

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
