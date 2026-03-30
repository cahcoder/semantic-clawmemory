#!/usr/bin/env node

const { Command } = require('commander');
const chalk = require('chalk');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');

const program = new Command();

program
  .name('semantic-clawmemory')
  .description('Universal semantic memory layer for AI CLI tools')
  .version('1.0.0');

// Find Python skill scripts
const SKILL_DIR = path.join(__dirname, '..', 'skill');

function runPython(script, args = []) {
  return new Promise((resolve, reject) => {
    const py = spawn('python3', [path.join(SKILL_DIR, script), ...args], {
      stdio: 'inherit',
      shell: false
    });
    
    py.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Script exited with code ${code}`));
    });
    
    py.on('error', reject);
  });
}

program
  .command('search <query>')
  .description('Query semantic memory')
  .option('-p, --project <name>', 'Project to search in')
  .option('-n, --limit <number>', 'Max results', '10')
  .action(async (query, opts) => {
    const args = [query];
    if (opts.project) args.push('--project', opts.project);
    if (opts.limit) args.push('--limit', opts.limit);
    
    try {
      await runPython('memory_search.py', args);
    } catch (e) {
      console.error(chalk.red('Error:'), e.message);
      process.exit(1);
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
  .description('Initialize semantic-clawmemory')
  .action(() => {
    console.log(chalk.green('Initializing semantic-clawmemory...'));
    console.log('Python dependencies will be installed on first use.');
    console.log(chalk.gray('Location: ~/.memory/chroma'));
  });

program.parse(process.argv);
