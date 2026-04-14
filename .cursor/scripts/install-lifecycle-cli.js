#!/usr/bin/env node
'use strict';

const path = require('path');

const {
  DEFAULT_REPO_ROOT,
  buildDoctorReport,
  repairInstalledStates,
} = require('./lib/install-lifecycle');

function parseArgs(argv) {
  const parsed = {
    command: null,
    repoRoot: DEFAULT_REPO_ROOT,
    projectRoot: process.cwd(),
    homeDir: process.env.HOME,
    dryRun: true,
    json: false,
  };

  const args = argv.slice(2);
  if (args.length === 0) {
    throw new Error('Expected a command: doctor or repair');
  }

  function readValue(flagName, index, fallbackValue) {
    const nextValue = args[index + 1];
    if (!nextValue || nextValue.startsWith('--')) {
      throw new Error(`Missing value for ${flagName}`);
    }
    return nextValue || fallbackValue;
  }

  parsed.command = args[0];
  for (let index = 1; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--repo-root') {
      parsed.repoRoot = readValue(arg, index, parsed.repoRoot);
      index += 1;
    } else if (arg === '--project-root') {
      parsed.projectRoot = readValue(arg, index, parsed.projectRoot);
      index += 1;
    } else if (arg === '--home-dir') {
      parsed.homeDir = readValue(arg, index, parsed.homeDir);
      index += 1;
    } else if (arg === '--apply') {
      parsed.dryRun = false;
    } else if (arg === '--json') {
      parsed.json = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  parsed.repoRoot = path.resolve(parsed.repoRoot);
  parsed.projectRoot = path.resolve(parsed.projectRoot);
  return parsed;
}

function printReport(report, asJson) {
  if (asJson) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return;
  }

  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

function main() {
  try {
    const args = parseArgs(process.argv);
    const sharedOptions = {
      repoRoot: args.repoRoot,
      projectRoot: args.projectRoot,
      homeDir: args.homeDir,
      allowMissingManifests: true,
    };

    if (args.command === 'doctor') {
      printReport(buildDoctorReport(sharedOptions), args.json);
      return;
    }

    if (args.command === 'repair') {
      printReport(repairInstalledStates({ ...sharedOptions, dryRun: args.dryRun }), args.json);
      return;
    }

    throw new Error(`Unsupported command: ${args.command}`);
  } catch (error) {
    const payload = {
      status: 'error',
      message: error && error.message ? error.message : String(error),
    };
    process.stderr.write(`${JSON.stringify(payload)}\n`);
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}
