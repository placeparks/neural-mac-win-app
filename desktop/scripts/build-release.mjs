import { spawnSync } from 'node:child_process';
import process from 'node:process';

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: false,
    ...options,
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

if (process.platform === 'win32') {
  run('powershell', ['-ExecutionPolicy', 'Bypass', '-File', 'scripts/build-sidecar-win.ps1']);
  run('cmd.exe', ['/d', '/s', '/c', 'npm run build']);
} else {
  run('bash', ['scripts/build-sidecar.sh']);
  run('npm', ['run', 'build']);
}
