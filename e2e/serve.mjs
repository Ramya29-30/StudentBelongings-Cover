// Starts the backend against a throw-away database for the browser tests (cross-platform: Windows, Linux, macOS).
import { spawn } from 'node:child_process';
import { mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const backend = resolve(import.meta.dirname, '..', 'backend');
const tmp = mkdtempSync(join(tmpdir(), 'sbc-e2e-'));
const win = process.platform === 'win32';
const venvPy = join(backend, '.venv', win ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.SBC_PYTHON || (existsSync(venvPy) ? venvPy : win ? 'python' : 'python3');
const port = process.env.E2E_PORT || '8765';
const child = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], {
  cwd: backend, stdio: 'inherit',
  env: { ...process.env, APP_ENV: 'test', SEED_DEMO_DATA: 'true', AI_PROVIDER: 'none', AI_VERIFY_MODE: 'dev_simulation', DATABASE_URL: `sqlite:///${join(tmp, 'e2e.db').replaceAll('\\', '/')}`,
         UPLOAD_DIR: join(tmp, 'uploads'), SECRET_KEY: 'e2e-secret-not-for-production-use-0123456789', LOG_LEVEL: 'WARNING' },
});
const stop = () => child.kill();
process.on('SIGTERM', stop); process.on('SIGINT', stop); process.on('exit', stop);
child.on('exit', code => process.exit(code ?? 0));
