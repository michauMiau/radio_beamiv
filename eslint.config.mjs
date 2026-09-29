// ESLint flat config for the Sendspin Radio mod.
//
// The mod is not a standalone npm project: it ships inside BeamNG's Vue bundle
// and is linted straight from source, so the config below only needs to know
// which globals the BeamNG CEF page provides and which files are Vue SFCs.
import js from '@eslint/js';
import globals from 'globals';
import vueParser from 'vue-eslint-parser';
import vuePlugin from 'eslint-plugin-vue';

export default [
  {
    ignores: [
      'node_modules/**',
      'sendspin-radio.zip',
      // Vendored, minified SDK bundle built from @sendspin/sendspin-js.
      'mod/ui/ui-vue/mods/SendspinRadio/lib/**',
      'dist/**',
    ],
  },
  js.configs.recommended,
  ...vuePlugin.configs['flat/recommended'],
  {
    files: ['**/*.js', '**/*.vue'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parser: vueParser,
      parserOptions: {
        parser: js.parser,
        ecmaVersion: 2022,
        sourceType: 'module',
      },
      globals: {
        ...globals.browser,
        // BeamNG injects the page bridge; the mod talks to the game through it.
        bngVue: 'readonly',
        BngBinding: 'readonly',
        $: 'readonly',
        angular: 'readonly',
        ng: 'readonly',
      },
    },
    rules: {
      // Unused args are often there to document a callback's signature.
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      eqeqeq: ['error', 'smart'],
      'no-var': 'error',
      'prefer-const': 'error',
      // Debug leftovers in shipped mod code are bugs, not style.
      // `info` is kept for the one deliberate startup diagnostic in index.js.
      'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
      'no-debugger': 'error',
      'no-alert': 'error',
    },
  },
  {
    // Vue SFCs: the template is compiled by BeamNG, so vue/no-unused-vars on
    // auto-generated refs would be noise.
    files: ['**/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'error',
      // `const props = defineProps(...)` is read by the template, which the
      // plain JS no-unused-vars rule cannot see. Turning it off only for SFCs
      // keeps the rule everywhere it actually works.
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', caughtErrors: 'none', varsIgnorePattern: '^props$' }],
      // Pure formatting preferences. BeamNG ships no Prettier, so these rules
      // only produce churn without a tool that can apply them; keeping them on
      // would bury real findings under 70 layout warnings.
      'vue/max-attributes-per-line': 'off',
      'vue/html-self-closing': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-indent': 'off',
      'vue/attributes-order': 'off',
      'vue/html-closing-bracket-newline': 'off',
    },
  },
];
