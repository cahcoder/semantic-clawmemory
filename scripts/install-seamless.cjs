#!/usr/bin/env node
/**
 * install-seamless.js - Install agents-memory daemon + OpenClaw managed hook
 * 
 * This is the post-install step that runs after `npm install -g agents-memory`
 * 
 * What it does:
 * 1. Installs daemon systemd service (Type=forking + PIDFile)
 * 2. Installs OpenClaw managed hook at ~/.openclaw/hooks/agents-memory/
 * 3. Copies skill files to skill/ dir for CLI access
 * 
 * IMPORTANT: This installs a MANAGED HOOK, NOT a plugin.
 * - Plugins: ~/.openclaw/extensions/
 * - Managed hooks: ~/.openclaw/hooks/
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || require('os').homedir();
const PLUGIN_ID = 'agents-memory';
const SERVICE_NAME = 'agents-memory-daemon';

// Paths
const MEMORY_DIR = path.join(HOME, '.memory', 'agents-memory');
const PID_FILE = path.join(MEMORY_DIR, 'daemon.pid');
const SOCKET_FILE = path.join(MEMORY_DIR, 'daemon.sock');
const OPENCLAW_HOOKS_DIR = path.join(HOME, '.openclaw', 'hooks');
const OPENCLAW_HOOK_DIR = path.join(OPENCLAW_HOOKS_DIR, PLUGIN_ID);
const OPENCLAW_CONFIG = path.join(HOME, '.openclaw', 'openclaw.json');

// Resolve package root dynamically
function getPackageRoot() {
  // 1. Try npm global prefix
  try {
    const globalPrefix = execSync('npm root -g', { encoding: 'utf8' }).trim();
    const globalPath = path.join(globalPrefix, 'agents-memory');
    if (fs.existsSync(path.join(globalPath, 'scripts', 'memory_daemon.py'))) {
      return globalPath;
    }
  } catch (e) {}

  // 2. Try __dirname (scripts/ -> package root)
  if (__dirname) {
    const scriptsDir = path.dirname(__dirname);
    if (fs.existsSync(path.join(scriptsDir, 'scripts', 'memory_daemon.py'))) {
      return scriptsDir;
    }
  }

  // 3. Environment variable
  if (process.env.AGENTS_MEMORY_ROOT) {
    return process.env.AGENTS_MEMORY_ROOT;
  }

  throw new Error(
    'Cannot find agents-memory package.\n' +
    'Try: npm install -g agents-memory'
  );
}

// ───────────────────────────────────────────────────────────────
// SYSTEMD SERVICE (Type=forking + PIDFile)
// ───────────────────────────────────────────────────────────────
function getSystemdUnit(daemonScript) {
  return `[Unit]
Description=Agents Memory Daemon (semantic memory for AI CLI tools)
After=network.target

[Service]
Type=forking
PIDFile=${PID_FILE}
ExecStartPre=/bin/mkdir -p ${MEMORY_DIR}
ExecStart=/usr/bin/python3 ${daemonScript} --daemon
ExecStop=/bin/kill -TERM $MAINPID
Environment="AGENTS_MEMORY_RUNTIME_DIR=${MEMORY_DIR}"
Environment="PYTHONPATH=${getPackageRoot()}/scripts"
Restart=always
RestartSec=5

[Install]
WantedBy=default.target`;
}

function installDaemon() {
  const PKG = getPackageRoot();
  const DAEMON_SCRIPT = path.join(PKG, 'scripts', 'memory_daemon.py');
  const SERVICE_FILE = path.join(HOME, '.config', 'systemd', 'user', `${SERVICE_NAME}.service`);

  console.log('\n[1/3] Installing daemon service...');
  console.log(`  Package root: ${PKG}`);
  console.log(`  Daemon script: ${DAEMON_SCRIPT}`);
  console.log(`  Memory dir: ${MEMORY_DIR}`);
  console.log(`  Socket: ${SOCKET_FILE}`);

  // Ensure memory directory
  fs.mkdirSync(MEMORY_DIR, { recursive: true, mode: 0o700 });

  // Write systemd unit (Type=forking is critical for auto-restart)
  fs.writeFileSync(SERVICE_FILE, getSystemdUnit(DAEMON_SCRIPT));
  console.log(`  Service file: ${SERVICE_FILE}`);

  // Enable and start
  try {
    execSync('systemctl --user daemon-reload', { stdio: 'pipe' });
    execSync(`systemctl --user enable ${SERVICE_NAME}.service`, { stdio: 'pipe' });
    execSync(`systemctl --user start ${SERVICE_NAME}.service`, { stdio: 'pipe' });
    console.log('  ✅ Daemon service installed and started');
    return true;
  } catch (e) {
    try {
      execSync(`systemctl --user restart ${SERVICE_NAME}.service`, { stdio: 'pipe' });
      console.log('  ✅ Daemon service restarted');
      return true;
    } catch (e2) {
      console.log('  ⚠️  Could not start systemd service');
      console.log('      Manual start: agents-memory daemon-start');
      return false;
    }
  }
}

// ───────────────────────────────────────────────────────────────
// OPENCLAW MANAGED HOOK (NOT plugin)
// ───────────────────────────────────────────────────────────────
function installOpenClawHook() {
  const PKG = getPackageRoot();
  const HOOK_SRC = path.join(PKG, 'hook-packs', 'agents-memory');
  const HOOK_SRC_LEGACY = path.join(PKG, 'hooks', 'agents-memory'); // fallback

  console.log('\n[2/3] Installing OpenClaw managed hook...');
  console.log(`  Source: ${HOOK_SRC}`);

  // Check if hook-packs exists
  if (!fs.existsSync(HOOK_SRC)) {
    console.log('  ⚠️  hook-packs/agents-memory not found in package');
    // Try legacy location
    if (fs.existsSync(HOOK_SRC_LEGACY)) {
      console.log(`  Trying legacy: ${HOOK_SRC_LEGACY}`);
    } else {
      console.log('  ⚠️  No hook source found - managed hook not installed');
      return false;
    }
  }

  // Ensure hooks directory
  fs.mkdirSync(OPENCLAW_HOOKS_DIR, { recursive: true });
  fs.mkdirSync(OPENCLAW_HOOK_DIR, { recursive: true });

  // Copy hook files (dereference symlinks to avoid symlink issues)
  const srcDir = fs.existsSync(HOOK_SRC) ? HOOK_SRC : HOOK_SRC_LEGACY;
  const files = fs.readdirSync(srcDir);
  for (const file of files) {
    const src = path.join(srcDir, file);
    const dst = path.join(OPENCLAW_HOOK_DIR, file);
    if (fs.statSync(src).isDirectory()) {
      fs.rmSync(dst, { recursive: true, force: true });
      fs.cpSync(src, dst, { recursive: true });
    } else {
      fs.copyFileSync(src, dst);
    }
  }
  console.log(`  ✅ Hook installed to: ${OPENCLAW_HOOK_DIR}`);
  console.log('  ✅ Files: HOOK.md, handler.js');

  // Verify critical files
  const required = ['HOOK.md', 'handler.js'];
  for (const f of required) {
    const fp = path.join(OPENCLAW_HOOK_DIR, f);
    if (!fs.existsSync(fp)) {
      console.log(`  ⚠️  Missing: ${f}`);
    }
  }

  return true;
}

// ───────────────────────────────────────────────────────────────
// COPY SKILL FILES
// ───────────────────────────────────────────────────────────────
function installSkill() {
  const PKG = getPackageRoot();
  const SKILL_SRC = path.join(PKG, 'skill');
  const SKILL_DST = path.join(HOME, '.npm-global', 'lib', 'node_modules', 'agents-memory', 'skill');

  console.log('\n[3/3] Installing skill files...');

  if (!fs.existsSync(SKILL_SRC)) {
    console.log('  ℹ️  No skill/ directory in package (optional)');
    return false;
  }

  fs.mkdirSync(path.dirname(SKILL_DST), { recursive: true });
  fs.rmSync(SKILL_DST, { recursive: true, force: true });
  fs.cpSync(SKILL_SRC, SKILL_DST, { recursive: true });
  console.log(`  ✅ Skill installed to: ${SKILL_DST}`);
  return true;
}

// ───────────────────────────────────────────────────────────────
// MAIN
// ───────────────────────────────────────────────────────────────
function main() {
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║         agents-memory Seamless Installer                 ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');

  const daemonOk = installDaemon();
  const hookOk = installOpenClawHook();
  const skillOk = installSkill();

  console.log('\n╔═══════════════════════════════════════════════════════════╗');
  console.log('║                 Installation Summary                     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log(`  Daemon service:  ${daemonOk ? '✅ Installed' : '⚠️  Skipped'}`);
  console.log(`  OpenClaw hook:   ${hookOk ? '✅ Installed' : '⚠️  Skipped'}`);
  console.log(`  Skill files:     ${skillOk ? '✅ Installed' : '⚠️  Skipped'}`);

  if (daemonOk && hookOk) {
    console.log('\n✅ Setup complete!');
    console.log('\n╔═══════════════════════════════════════════════════════════╗');
    console.log('║         MANUAL CONFIGURATION REQUIRED                   ║');
    console.log('╚═══════════════════════════════════════════════════════════╝');
    console.log('\n⚠️  You must add this to ~/.openclaw/openclaw.json:');
    console.log('\n  1. Open: nano ~/.openclaw/openclaw.json');
    console.log('\n  2. Add to "hooks.internal.entries":');
    console.log(`
     "agents-memory": {
       "enabled": true
     }
  `);
    console.log('\n  3. Add to "plugins.entries":');
    console.log(`
     "agents-memory": {
       "enabled": true
     }
  `);
    console.log('\n  4. (Optional) Remove legacy entries if present:');
    console.log('     - hooks.internal.entries.session-memory');
    console.log('     - hooks.internal.entries.semantic-memory');
    console.log('     - plugins.installs.agents-memory');
    console.log('\n  5. Restart OpenClaw gateway:');
    console.log('     nohup openclaw gateway restart > /dev/null 2>&1 &');
    console.log('\n  6. Verify hook is loaded:');
    console.log('     openclaw hooks list');
    console.log('\n  7. Test memory pipeline:');
    console.log('     Send a message to your bot - hook should trigger');
  } else {
    console.log('\n⚠️  Installation incomplete.');
    if (!daemonOk) {
      console.log('  - Daemon: Try starting manually with: agents-memory daemon-start');
    }
    if (!hookOk) {
      console.log('  - Hook: Check that hook-packs/agents-memory exists in package');
    }
  }
}

main();
