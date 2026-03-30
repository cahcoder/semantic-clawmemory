#!/usr/bin/env node

const { Command } = require('commander');
const chalk = require('chalk');
const ora = require('ora');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');
const fs = require('fs');

// Load version from package.json
const packageJson = require(path.join(__dirname, '..', 'package.json'));
const program = new Command();

program
  .name('agents-memory')
  .description('Universal semantic memory layer for AI CLI tools')
  .version(packageJson.version);

// Support -v and -h as aliases
program
  .alias('am')
  .option('-v', 'output the version number', () => {
    console.log(packageJson.version);
    process.exit(0);
  })
  .option('-h', 'display help for command', () => {
    program.outputHelp();
    process.exit(0);
  });

// Update command - check for new version
const updateCmd = program.command('update').description('Check for updates and upgrade agents-memory');
updateCmd.action(() => {
  const { execSync } = require('child_process');
  console.log(chalk.blue('🔄 Checking for updates...'));
  try {
    const current = packageJson.version;
    const latest = execSync('npm view agents-memory version', { encoding: 'utf8' }).trim();
    if (current === latest) {
      console.log(chalk.green(`✅ Already on latest version (${current})`));
    } else {
      console.log(chalk.yellow(`📦 Current: ${current} → Latest: ${latest}`));
      console.log('Run: npm install -g agents-memory@latest --foreground-scripts');
    }
  } catch (e) {
    console.error(chalk.red('Failed to check for updates'));
  }
});

// Find Python skill scripts - works for both local dev and global npm install
function findSkillDir() {
  // Local dev: /srv/apps/agents-memory/src/cli.js → parent has skill/
  const localSkill = path.join(__dirname, '..', 'skill');
  if (fs.existsSync(localSkill)) return localSkill;

  // Global npm: /usr/lib/node_modules/agents-memory/src/cli.js
  const globalSkill = path.join(__dirname, '..', 'skill');
  if (fs.existsSync(globalSkill)) return globalSkill;

  // Fallback: look in common global locations
  const globalPaths = [
    '/usr/lib/node_modules/agents-memory/skill',
    '/usr/local/lib/node_modules/agents-memory/skill',
    path.join(os.homedir(), '.npm-global/lib/node_modules/agents-memory/skill')
  ];

  for (const p of globalPaths) {
    if (fs.existsSync(p)) return p;
  }

  // Last resort: assume local
  return localSkill;
}

const SKILL_DIR = findSkillDir();

// Validate skill directory exists
if (!fs.existsSync(SKILL_DIR)) {
  console.error(chalk.red('Error: skill/ directory not found.'));
  console.error(chalk.gray('Please ensure agents-memory is properly installed.'));
  process.exit(1);
}

function runPython(script, args = [], showSpinner = true) {
  return new Promise((resolve, reject) => {
    const spinner = showSpinner ? ora({
      text: chalk.gray(`Running ${script}...`),
      spinner: 'dots'
    }).start() : null;

    const py = spawn('python3', [path.join(SKILL_DIR, script), ...args], {
      stdio: ['pipe', 'pipe', 'pipe'],
      shell: false
    });

    let stdout = '';
    let stderr = '';

    py.stdout.on('data', (data) => { stdout += data.toString(); });
    py.stderr.on('data', (data) => { stderr += data.toString(); });

    py.on('close', (code) => {
      if (spinner) spinner.stop();

      // Print stdout/stderr from Python scripts (they handle their own formatting)
      if (stdout) process.stdout.write(stdout);
      if (stderr) process.stderr.write(stderr);

      if (code === 0) resolve();
      else reject(new Error(`Script exited with code ${code}`));
    });

    py.on('error', (err) => {
      if (spinner) spinner.fail(chalk.red('Error'));
      reject(err);
    });
  });
}

// Daemon-based search for fast responses (model stays loaded in memory)
const DAEMON_SOCKET = '/tmp/agents-memory-daemon.sock';

// Check if daemon is running (async)
function isDaemonRunning() {
  return new Promise((resolve) => {
    try {
      const net = require('net');
      const client = new net.Socket();
      let resolved = false;
      
      client.connect(DAEMON_SOCKET, () => {
        client.write(JSON.stringify({cmd: 'ping'}) + '\n');
      });
      
      client.setTimeout(2000);
      
      client.on('data', () => {
        if (!resolved) {
          resolved = true;
          client.destroy();
          resolve(true);
        }
      });
      
      client.on('error', () => {
        if (!resolved) {
          resolved = true;
          client.destroy();
          resolve(false);
        }
      });
      
      client.on('timeout', () => {
        if (!resolved) {
          resolved = true;
          client.destroy();
          resolve(false);
        }
      });
    } catch (e) {
      resolve(false);
    }
  });
}

// Sync check if daemon socket exists
function isDaemonSocketExists() {
  const fs = require('fs');
  return fs.existsSync(DAEMON_SOCKET);
}

// Auto-start daemon if not running (async)
async function ensureDaemon() {
  if (await isDaemonRunning()) return;
  
  const { spawn } = require('child_process');
  const fs = require('fs');
  const path = require('path');
  
  // Find daemon script - check multiple locations
  const possiblePaths = [
    path.join(SKILL_DIR, '..', 'scripts', 'memory_daemon.py'),
    '/srv/apps/semantic-clawmemory/scripts/memory_daemon.py',
    path.join(os.homedir(), '.npm-global', 'lib', 'node_modules', 'agents-memory', 'scripts', 'memory_daemon.py')
  ];
  
  let daemonPath = null;
  for (const p of possiblePaths) {
    if (fs.existsSync(p)) {
      daemonPath = p;
      break;
    }
  }
  
  if (!daemonPath) {
    console.error(chalk.yellow('Daemon not found, install may be incomplete'));
    return;
  }
  
  // Start daemon in background using setsid
  try {
    require('child_process').spawn('setsid', ['python3', daemonPath, '--daemon'], {
      detached: true,
      stdio: 'ignore',
      shell: false
    }).unref();
  } catch (e) {
    // Fallback: try direct spawn
    try {
      require('child_process').spawn('python3', [daemonPath, '--daemon'], {
        detached: true,
        stdio: 'ignore'
      }).unref();
    } catch (e2) {
      console.error(chalk.yellow('Could not auto-start daemon'));
    }
  }
}

async function daemonSearch(query, project, limit) {
  await ensureDaemon();  // Auto-start if needed
  
  return new Promise((resolve, reject) => {
    const net = require('net');
    const client = new net.Socket();
    
    client.connect(DAEMON_SOCKET, () => {
      const cmd = {
        cmd: 'search',
        args: { query, project, limit: parseInt(limit) || 10 }
      };
      client.write(JSON.stringify(cmd) + '\n');
    });
    
    let data = '';
    client.on('data', (chunk) => { data += chunk.toString(); });
    client.on('end', () => {
      try {
        const result = JSON.parse(data);
        if (result.ok) {
          resolve(result.data);
        } else {
          reject(new Error(result.error || 'Daemon error'));
        }
      } catch (e) {
        reject(new Error('Invalid daemon response'));
      }
      client.destroy();
    });
    client.on('error', (err) => {
      reject(err);
      client.destroy();
    });
    
    client.setTimeout(30000);
    client.on('timeout', () => {
      client.destroy();
      reject(new Error('Daemon timeout'));
    });
  });
}

function formatDaemonResults(results) {
  if (!results || results.length === 0) {
    console.log(chalk.gray('No results found.'));
    return;
  }
  
  for (const r of results) {
    const sim = (r.similarity || 0).toFixed(3);
    const col = r.collection || 'unknown';
    const content = r.content || '';
    
    // Truncate long content
    const display = content.length > 120 ? content.slice(0, 120) + '...' : content;
    
    // Parse content - usually "Problem: X\n\nSolution: Y"
    const lines = display.split('\n');
    let problemLine = lines[0] || '';
    let solutionLine = lines.slice(1).join(' ').trim() || '';
    
    if (problemLine.startsWith('Problem:')) {
      problemLine = problemLine.slice(8).trim();
    }
    
    console.log(chalk.cyan(`[${col}]`) + chalk.gray(` sim=${sim}`));
    if (problemLine) console.log(`  ${chalk.bold(problemLine)}`);
    if (solutionLine) console.log(chalk.gray(`  → ${solutionLine.slice(0, 100)}`));
    console.log();
  }
}

program
  .command('search <query>')
  .description('Query semantic memory')
  .option('-p, --project <name>', 'Project to search in')
  .option('-n, --limit <number>', 'Max results', '10')
  .action(async (query, opts) => {
    const spinner = ora({
      text: chalk.gray('Searching memory...'),
      spinner: 'dots'
    }).start();
    
    try {
      const results = await daemonSearch(query, opts.project, opts.limit);
      spinner.stop();
      formatDaemonResults(results);
    } catch (e) {
      spinner.stop();
      // Fallback to Python subprocess if daemon not available
      const args = [query];
      if (opts.project) args.push('--project', opts.project);
      if (opts.limit) args.push('--limit', opts.limit);
      try {
        await runPython('memory_search.py', args);
      } catch (e2) {
        console.error(chalk.red('Error:'), e.message);
        process.exit(1);
      }
    }
  });

program
  .command('write <problem>')
  .description('Store a learning to memory')
  .option('-s, --solution <code>', 'Solution or sample code')
  .option('-t, --type <type>', 'Entry type', 'solution')
  .option('-p, --project <name>', 'Project name')
  .option('-l, --logic <explanation>', 'Why/how it works')
  .action(async (problem, opts) => {
    const args = [problem];
    if (opts.solution) args.push('--solution', opts.solution);
    if (opts.type) args.push('--type', opts.type);
    if (opts.project) args.push('--project', opts.project);
    if (opts.logic) args.push('--logic', opts.logic);

    try {
      await runPython('memory_write.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
    }
  });

program
  .command('pre <input>')
  .description('PRE-LLM hook: query and inject context')
  .option('-p, --project <name>', 'Project name')
  .action(async (input, opts) => {
    const args = [input];
    if (opts.project) args.push('--project', opts.project);

    try {
      await runPython('memory_pre_llm.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
    }
  });

program
  .command('post <input> <response>')
  .description('POST-LLM hook: analyze and store learning')
  .option('-p, --project <name>', 'Project name')
  .action(async (input, response, opts) => {
    const args = [input, response];
    if (opts.project) args.push('--project', opts.project);

    try {
      await runPython('memory_post_llm.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
    }
  });

program
  .command('bootstrap <project>')
  .description('Bootstrap new project memory')
  .option('-a, --architecture <desc>', 'Architecture description')
  .option('-t, --tech-stack <stack>', 'Tech stack')
  .option('-d, --domain <domain>', 'Project domain')
  .action(async (project, opts) => {
    const args = [project];
    if (opts.architecture) args.push('--architecture', opts.architecture);
    if (opts.techStack) args.push('--tech-stack', opts.techStack);
    if (opts.domain) args.push('--domain', opts.domain);

    try {
      await runPython('memory_bootstrap.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
    }
  });

program
  .command('gc')
  .description('Garbage collection')
  .option('--stats', 'Show statistics')
  .option('--dedup', 'Run deduplication')
  .option('--decay', 'Apply importance decay')
  .option('--archive', 'Archive old entries')
  .option('--all', 'Run all cleanup')
  .action(async (opts) => {
    let args = [];
    if (opts.stats) args.push('--stats');
    if (opts.dedup) args.push('--dedup');
    if (opts.decay) args.push('--decay');
    if (opts.archive) args.push('--archive');
    if (opts.all) args.push('--all');

    try {
      await runPython('memory_gc.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
    }
  });

program
  .command('init')
  .description('Initialize agents-memory (or run setup again)')
  .action(() => {
    const { execSync } = require('child_process');
    const fs = require('fs');
    const path = require('path');
    const os = require('os');

    const GREEN = '\x1b[32m';
    const RED = '\x1b[31m';
    const YELLOW = '\x1b[33m';
    const CYAN = '\x1b[36m';
    const RESET = '\x1b[0m';

    console.log('');
    console.log(`${CYAN}╔══════════════════════════════════════════╗${RESET}`);
    console.log(`${CYAN}║   agents-memory setup             ║${RESET}`);
    console.log(`${CYAN}╚══════════════════════════════════════════╝${RESET}`);
    console.log('');

    // Check Python
    try {
      execSync('python3 --version', { stdio: 'pipe' });
    } catch (e) {
      console.error(`${RED}❌ Python 3 not found${RESET}`);
      return;
    }
    console.log(`${GREEN}✅${RESET} Python 3 found`);

    // Check pip
    let pipCmd = 'pip3';
    try {
      execSync('pip3 --version', { stdio: 'pipe' });
    } catch (e) {
      pipCmd = 'pip';
      try {
        execSync('pip --version', { stdio: 'pipe' });
      } catch (e2) {
        console.error(`${RED}❌ pip not found${RESET}`);
        return;
      }
    }
    console.log(`${GREEN}✅${RESET} pip found`);

    const deps = [
      { name: 'chromadb', desc: 'Vector database' },
      { name: 'sentence-transformers', desc: 'Embedding model' },
      { name: 'python-dateutil', desc: 'Date utilities' },
      { name: 'pyyaml', desc: 'YAML parser' }
    ];

    console.log('');
    console.log(`${CYAN}📦 Installing Python dependencies:${RESET}`);
    console.log('');

    for (let i = 0; i < deps.length; i++) {
      const dep = deps[i];
      const num = i + 1;
      process.stdout.write(`   [${num}/${deps.length}] ${dep.name} (${dep.desc})... `);

      let installed = false;
      for (const flags of ['--break-system-packages', '--user', '']) {
        try {
          const cmd = `${pipCmd} install ${flags} ${dep.name}`.trim();
          execSync(cmd, { stdio: 'pipe', env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1' } });
          installed = true;
          break;
        } catch (e) {}
      }

      if (installed) {
        console.log(`${GREEN}✅${RESET}`);
      } else {
        console.log(`${RED}❌${RESET}`);
      }
    }

    console.log('');
    const memDir = path.join(os.homedir(), '.memory', 'chroma');
    fs.mkdirSync(memDir, { recursive: true });
    console.log(`${GREEN}✅${RESET} Memory directory: ${memDir}`);

    // Create AGENTS.md in current working directory
    console.log('');
    console.log(`${CYAN}📝 Creating AGENTS.md in current directory:${RESET}`);
    const { execSync: exec } = require('child_process');
    const cwd = process.cwd();
    const agentsPath = path.join(cwd, 'AGENTS.md');

    const memorySection = `

---

## Semantic Memory

### Memory Setup
\`\`\`bash
export MEMORY_DIR="$HOME/.memory/chroma"
export SKILL_DIR="~/.npm-global/lib/node_modules/agents-memory/skill"
\`\`\`

### PRE-LLM Hook (Before AI thinks)
\`\`\`bash
agents-memory pre "{task description}"
\`\`\`
When results found, inject them into context.

### POST-LLM Hook (After AI responds)
\`\`\`bash
agents-memory post "{problem solved}" "{solution}"
\`\`\`
Only store generic patterns, not specific values.

### Essential Commands
- \`agents-memory search <query>\`  - Search memory
- \`agents-memory write <problem> <solution>\` - Store learning
- \`agents-memory bootstrap <project>\` - Init project memory
`;

    if (fs.existsSync(agentsPath)) {
      const content = fs.readFileSync(agentsPath, 'utf8');
      if (content.includes('## Semantic Memory') || content.includes('agents-memory')) {
        console.log(`${YELLOW}⚠${RESET} AGENTS.md already has semantic memory section - skipped`);
      } else {
        fs.appendFileSync(agentsPath, memorySection);
        console.log(`${GREEN}✅${RESET} Appended semantic memory to AGENTS.md`);
      }
    } else {
      fs.writeFileSync(agentsPath, `# Semantic Memory\n${memorySection}\n`);
      console.log(`${GREEN}✅${RESET} Created AGENTS.md with semantic memory`);
    }

    console.log('');
    console.log(`${CYAN}╔══════════════════════════════════════════╗${RESET}`);
    console.log(`${CYAN}║${RESET}   ✅ agents-memory ready!            ${CYAN}║${RESET}`);
    console.log(`${CYAN}╚══════════════════════════════════════════╝${RESET}`);
    console.log('');
  });

program
  .command('init-project')
  .description('Create or append AGENTS.md section for semantic memory')
  .action(() => {
    const fs = require('fs');
    const path = require('path');
    const os = require('os');

    const memorySection = `

---

## Semantic Memory

### Memory Setup
\`\`\`bash
export MEMORY_DIR="$HOME/.memory/chroma"
export SKILL_DIR="~/.npm-global/lib/node_modules/agents-memory/skill"
\`\`\`

### PRE-LLM Hook (Before AI thinks)
\`\`\`bash
agents-memory pre "{task description}"
\`\`\`
When results found, inject them into context.

### POST-LLM Hook (After AI responds)
\`\`\`bash
agents-memory post "{problem solved}" "{solution}"
\`\`\`
Only store generic patterns, not specific values.

### Essential Commands
- \`agents-memory search <query>\`  - Search memory
- \`agents-memory write <problem> <solution>\` - Store learning
- \`agents-memory bootstrap <project>\` - Init project memory
`;

    const targetPath = path.join(process.cwd(), 'AGENTS.md');

    if (fs.existsSync(targetPath)) {
      // Check if already has semantic memory section
      const content = fs.readFileSync(targetPath, 'utf8');
      if (content.includes('## Semantic Memory') || content.includes('agents-memory')) {
        console.log(chalk.yellow('AGENTS.md already has semantic memory section'));
        console.log(chalk.green('✓ Skipped - no changes needed'));
        return;
      }
      // Append to existing file
      fs.appendFileSync(targetPath, memorySection);
      console.log(chalk.green('✓ Appended semantic memory to AGENTS.md'));
    } else {
      // Create new file
      fs.writeFileSync(targetPath, `# Semantic Memory\n${memorySection}\n`);
      console.log(chalk.green('✓ Created AGENTS.md with semantic memory'));
    }
    console.log(chalk.gray('AI CLI tools will now use semantic memory'));
  });

program.parse(process.argv);
