import test from 'node:test'; import assert from 'node:assert'
test('smoke: arithmetic for success rate display', () => { assert.equal(Math.round(0.6*100), 60) })
