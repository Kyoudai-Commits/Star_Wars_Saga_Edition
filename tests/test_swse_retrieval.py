"""Offline integration and policy regressions for the SWSE retrieval tools."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from tools.build_catalog import sha256
from tools.swse.cli import dispatch, main, serve
from tools.swse.constraints import evaluate, validate_ast, validate_character
from tools.swse.evaluation import run_evaluation
from tools.swse.repository import Repository
from tools.swse.store import build
from tools.swse.text import alias_key, plain, prereq_lines, safe_fts_query, strip_links, units

ROOT = Path(__file__).resolve().parents[1]


class TextAndConstraintTests(unittest.TestCase):
    def test_link_labels_preserve_parentheses_and_nested_images(self):
        text = '[Armor (Light)](https://example.org/Armor_(Light) "Armor (Light)") and [![](//example.org/x.png)](https://example.org/File:x)'
        self.assertEqual(strip_links(text).strip(), 'Armor (Light) and')
        self.assertEqual(plain('**Time:** [Swift Action](https://example.org/Swift_Action)'), 'Time: Swift Action')
        self.assertEqual(plain('2 * 3'), '2 * 3')

    def test_url_casing_namespace_disambiguators_not_collapsed(self):
        self.assertNotEqual(alias_key('https://swse.miraheze.org/wiki/Force_Storm'), alias_key('https://swse.miraheze.org/wiki/force_storm'))
        self.assertEqual(alias_key('https://swse.miraheze.org/wiki/Vornskr%27s_Ferocity'), alias_key("https://swse.miraheze.org/wiki/Vornskr's_Ferocity"))
        self.assertNotEqual(alias_key('https://swse.miraheze.org/wiki/Force_Storm_(FUCG)'), alias_key('https://swse.miraheze.org/wiki/Force_Storm'))
        self.assertNotEqual(alias_key('https://swse.miraheze.org/wiki/Armor'), alias_key('https://swse.miraheze.org/wiki/Category:Armor'))
        self.assertNotEqual(alias_key('https://swse.miraheze.org/wiki/Force_Storm?oldid=1'), alias_key('https://swse.miraheze.org/wiki/Force_Storm'))

    def test_table_unit_is_never_split_at_budget_or_curated_boundary(self):
        lines = ['## Rule', '', 'Check determines effect.', '', '| DC | Effect |', '| --- | --- |', '| 15 | One |', '| 20 | Two |']
        result = units(lines, 1, len(lines))
        table = next(unit for unit in result if unit.table)
        self.assertEqual((table.start, table.end), (5, 8))
        self.assertEqual(table.text.count('\n'), 3)
        with self.assertRaisesRegex(ValueError, 'split a Markdown table'):
            units(lines, 1, len(lines), {7})

    def test_prerequisite_parser_preserves_nested_lists_not_effect_text(self):
        lines = ['**Prerequisites:** Criteria:', '', '- **Minimum Level:** 7th', '- **Talents:** Any two from', '  - Awareness Talent Tree, or', '  - Survivor Talent Tree', '', '## Game Rule Information', 'Other text.']
        raw, spans = prereq_lines(lines, [[1, len(lines)]])
        self.assertIn('Any two', raw)
        self.assertIn('Survivor Talent Tree', raw)
        self.assertNotIn('Game Rule Information', raw)
        self.assertEqual(spans, [[1, 7]])

    def test_search_input_cannot_be_fts_or_sql_operators(self):
        expression = safe_fts_query('" OR 1=1; DROP TABLE entities; --')
        self.assertNotIn(';', expression)
        self.assertNotIn('TABLE entities;', expression)
        self.assertTrue(expression.startswith('"'))

    def test_three_valued_and_or(self):
        condition = {'op': 'gte', 'field': 'level', 'value': 7}
        special = {'op': 'fact', 'name': 'membership'}
        self.assertEqual(evaluate({'op': 'all', 'args': [condition, special]}, {'level': 6}, lambda _: None)['result'], 'not_met')
        self.assertEqual(evaluate({'op': 'all', 'args': [condition, special]}, {'level': 7}, lambda _: None)['result'], 'unknown')
        self.assertEqual(evaluate({'op': 'any', 'args': [condition, special]}, {'level': 7}, lambda _: None)['result'], 'met')
        self.assertEqual(evaluate({'op': 'any', 'args': [condition, special]}, {'level': 6}, lambda _: None)['result'], 'unknown')

    def test_partial_inventory_and_missing_inventory_are_unknown(self):
        ast = {'op': 'has', 'field': 'feats', 'value': 'Flurry'}
        self.assertEqual(evaluate(ast, {}, lambda _: None)['result'], 'unknown')
        self.assertEqual(evaluate(ast, {'feats': []}, lambda _: None)['result'], 'not_met')
        self.assertEqual(evaluate(ast, {'feats': [], 'inventories_complete': {'feats': False}}, lambda _: None)['result'], 'unknown')

    def test_boolean_stats_typos_and_invalid_expressions_rejected(self):
        for character in ({'level': True}, {'levle': 7}, {'facts': {'member': 'yes'}}, {'talents': [{'name': 'X', 'trree': 'Y'}]}):
            with self.subTest(character=character), self.assertRaises(ValueError):
                validate_character(character)
        for ast in ({'op': 'run_shell'}, {'op': 'gte', 'field': 'level', 'value': True}, {'op': 'any', 'args': []}):
            with self.subTest(ast=ast), self.assertRaises(ValueError):
                validate_ast(ast)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temp.name) / 'test.sqlite3'
        cls.report = build(ROOT, cls.database)
        cls.repo = Repository(ROOT, cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.repo.close()
        cls.temp.cleanup()

    def test_complete_golden_local_evidence_suite(self):
        report = run_evaluation(self.repo, ROOT, save=False)
        self.assertEqual(report['failed'], 0, [case for case in report['cases'] if case['status'] == 'failed'])
        self.assertEqual(report['passed'], report['case_count'])

    def test_counts_and_default_homebrew_exclusion(self):
        self.assertEqual(self.report['individual_talents'], 1142)
        self.assertEqual(len(self.report['homebrew_talents']), 5)
        self.assertEqual(self.repo.list_entities(kind='talent', limit=1)['total'], 1137)
        self.assertEqual(self.repo.list_entities(kind='talent', include_homebrew=True, limit=1)['total'], 1142)
        self.assertEqual(self.repo.list_entities(kind='heroic_class', limit=100)['total'], 5)
        self.assertEqual(self.repo.list_entities(kind='heroic_class', include_homebrew=True, limit=100)['total'], 7)

    def test_sibling_source_variants_and_entity_types_are_disambiguated(self):
        for name in ('Staggering Attack', 'Force Storm', 'Corruption', 'Intercept', 'Dark Transfer'):
            with self.subTest(name=name):
                result = self.repo.get(name)
                self.assertEqual(result['status'], 'ambiguous')
                self.assertEqual(len(result['choices']), 2)
        result = self.repo.get('Corruption', kind='destiny')
        self.assertEqual(result['entity']['entity_id'], 'destiny:corruption')
        self.assertNotIn('Make a Use the Force check', '\n'.join(c['text'] for c in result['evidence']))

    def test_source_facet_preserves_relevant_clarifications(self):
        result = self.repo.get('Rapid Strike', book='Core Rulebook')
        self.assertTrue(any(chunk['rule_role'] == 'clarification' for chunk in result['evidence']))
        self.assertTrue(any('Whirlwind Attack' in chunk['text'] for chunk in result['evidence']))

    def test_table_text_and_source_citations(self):
        result = self.repo.get('Move Object')
        table = next(chunk for chunk in result['evidence'] if chunk['has_table'])
        for dc in (15, 20, 25, 30, 35):
            self.assertIn(f'| {dc} |', table['text'])
        citation = table['citation']
        raw = (ROOT / citation['path']).read_text().splitlines()
        self.assertGreaterEqual(citation['start_line'], 1)
        self.assertLessEqual(citation['end_line'], len(raw))
        self.assertEqual(sha256((ROOT / citation['path']).read_bytes()), citation['file_sha256'])
        self.assertNotIn('https://', table['text'])

    def test_every_entity_and_chunk_has_valid_local_coordinates(self):
        for row in self.repo.connection.execute('SELECT data FROM entities'):
            entity = json.loads(row['data'])
            self.assertTrue(entity['citations'])
            for citation in entity['citations']:
                if 'row' in citation:
                    self.assertTrue((ROOT / citation['path']).is_file())
                else:
                    n = len((ROOT / citation['path']).read_text().splitlines())
                    self.assertTrue(1 <= citation['start_line'] <= citation['end_line'] <= n)
        for row in self.repo.connection.execute('SELECT data FROM chunks'):
            chunk = json.loads(row['data'])
            citation = chunk['citation']
            n = len((ROOT / citation['path']).read_text().splitlines())
            self.assertTrue(1 <= citation['start_line'] <= citation['end_line'] <= n)
            self.assertEqual(chunk['char_count'], len(chunk['text']))

    def test_homebrew_cannot_leak_via_parent_tree_bundle(self):
        result = self.repo.get('Survivor Talent Tree', expand=True)
        self.assertNotIn('Wilderness Medic', '\n'.join(chunk['text'] for chunk in result['evidence'] + result['context']))
        results = self.repo.search('Wilderness Medic', limit=500)
        self.assertFalse(any(item['passage_scope'] == 'homebrew' for item in results['items']))

    def test_optional_cannot_leak_via_parent_reference_bundle(self):
        result = self.repo.get('The Force', max_chars=200000)
        self.assertFalse(any(chunk['rule_role'] == 'optional_rule' for chunk in result['evidence']))
        self.assertNotIn('Unused Force Points do not carry over', '\n'.join(chunk['text'] for chunk in result['evidence']))
        result = self.repo.get('The Force', max_chars=200000, include_optional=True)
        self.assertTrue(any(chunk['rule_role'] == 'optional_rule' for chunk in result['evidence']))

    def test_book_source_does_not_bleed_between_sibling_talents(self):
        expert = self.repo.get('Expert Tracker', kind='talent')['entity']
        reset = self.repo.get('Reset Initiative', kind='talent')['entity']
        weak = self.repo.get('Weak Point', kind='talent')['entity']
        self.assertEqual(expert['declared_sources'], ['Core Rulebook'])
        self.assertEqual(reset['declared_sources'], ['Force Unleashed Campaign Guide'])
        self.assertEqual(weak['declared_sources'], ['Knights of the Old Republic Campaign Guide'])

    def test_pagination_is_exact_enumeration_with_no_duplicates(self):
        ids, offset, total = [], 0, None
        while offset is not None:
            result = self.repo.list_entities(kind='talent', tree='Awareness Talent Tree', limit=3, offset=offset)
            total = result['total']
            ids.extend(item['entity_id'] for item in result['items'])
            offset = result['next_offset']
        self.assertEqual(total, 8)
        self.assertEqual(len(ids), total)
        self.assertEqual(len(set(ids)), total)

    def test_action_and_class_filters_are_declared_not_inferred(self):
        result = self.repo.list_entities(kind='force_power', action='Swift Action', limit=500)
        self.assertGreater(result['total'], 0)
        for item in result['items']:
            entity = self.repo.get(item['entity_id'])['entity']
            self.assertTrue(any(field['text'] == 'Swift Action' for field in entity['mechanic_fields']['time']))
        result = self.repo.list_entities(kind='talent_tree', class_name='Scout', limit=100)
        self.assertGreater(result['total'], 0)
        self.assertTrue(any('not proof' in warning for warning in result['warnings']))

    def test_kind_scoped_short_tree_alias_does_not_make_class_ambiguous(self):
        self.assertEqual(self.repo.resolve('Bounty Hunter')['status'], 'resolved')
        self.assertEqual(self.repo.resolve('Bounty Hunter', kind='talent_tree')['entity']['entity_id'], 'talent_tree:bounty-hunter-talent-tree')

    def test_budget_omissions_are_explicit_and_no_partial_table_claimed(self):
        result = self.repo.get('Move Object', max_chars=20)
        self.assertFalse(result['complete_for_allowed_passages'])
        self.assertTrue(result['omitted_chunks'])
        self.assertLessEqual(result['emitted_characters'], 20)
        large = self.repo.connection.execute('SELECT chunk_id FROM chunks WHERE char_count>3200 LIMIT 1').fetchone()
        result = self.repo.chunk(large['chunk_id'], max_chars=20)
        self.assertEqual(result['status'], 'budget_too_small')

    def test_parent_context_budget_omissions_are_not_silently_complete(self):
        own = self.repo.get('Expert Tracker', kind='talent')
        budget = sum(chunk['char_count'] for chunk in own['evidence'])
        result = self.repo.get('Expert Tracker', kind='talent', expand=True, max_chars=budget)
        self.assertTrue(result['complete_for_entity_allowed_passages'])
        self.assertFalse(result['complete_for_requested_context'])
        self.assertFalse(result['complete_for_allowed_passages'])
        self.assertTrue(result['omitted_context_chunks'])
        self.assertLessEqual(result['emitted_characters'], budget)

    def test_workbook_variants_and_missing_prerequisite_summary_distinctions(self):
        a = self.repo.get('Staggering Attack', book='Scum and Villainy')
        b = self.repo.get('Staggering Attack', book='Galaxy at War')
        self.assertEqual([r['row'] for r in a['workbook_summaries']], [138])
        self.assertEqual([r['row'] for r in b['workbook_summaries']], [270])
        e = self.repo.get('Elite Trooper')['entity']
        self.assertIn('Armor Proficiency (Light)', e['prerequisites_raw'])
        self.assertEqual(len(self.report['ambiguous_or_unmatched_workbook_rows']), 1)
        self.assertEqual(self.report['ambiguous_or_unmatched_workbook_rows'][0]['label'], 'Dark Transfer')

    def test_coverage_distinguishes_embedded_review_from_absence(self):
        self.assertEqual(self.repo.coverage('Force Point')['status'], 'embedded_evidence')
        self.assertEqual(self.repo.coverage('Use the Force')['status'], 'insufficient_local_evidence')
        self.assertEqual(self.repo.coverage('Reflex Defense')['status'], 'document_gap_semantic_coverage_unreviewed')
        self.assertEqual(self.repo.coverage('A made up skill')['status'], 'no_curated_local_evidence')

    def test_constraints_do_not_count_forgeries_unknowns_duplicates_or_homebrew(self):
        base = {'level': 7, 'trained_skills': ['Survival']}
        forged = {**base, 'talents': [{'name': 'Acute Senses', 'tree': 'Commando Talent Tree'}, 'Unknown talent']}
        self.assertEqual(self.repo.check('Bounty Hunter', forged)['result'], 'unknown')
        repeated = {**base, 'talents': ['Acute Senses', 'Acute Senses']}
        self.assertEqual(self.repo.check('Bounty Hunter', repeated)['result'], 'not_met')
        self.assertEqual(self.repo.check('Force Storm', {})['result'], 'unknown')
        self.assertEqual(self.repo.check('Vehicular Combat', {})['result'], 'unknown')
        with self.assertRaises(ValueError):
            self.repo.check('Vehicular Combat', {'levle': 7})

    def test_all_reviewed_class_expressions_have_local_proof_and_special_facts(self):
        result = self.repo.list_entities(kind='prestige_class', reviewed_prerequisites=True, limit=100)
        self.assertEqual(result['total'], 30)
        for item in result['items']:
            entity = self.repo.get(item['entity_id'])['entity']
            validate_ast(entity['prerequisites_ast'])
            self.assertTrue(entity['prerequisite_citations'])
        result = self.repo.check('Jedi Knight', {'base_attack_bonus': 7, 'trained_skills': ['Use the Force'],
                                                 'feats': ['Force Sensitivity', 'Weapon Proficiency (Lightsabers)']})
        self.assertEqual(result['result'], 'unknown')

    def test_json_lines_adapter_recovers_after_bad_request(self):
        source = io.StringIO('not json\n' + json.dumps({'id': 2, 'method': 'get', 'params': {'name': 'Armored Defense'}}) + '\n')
        destination = io.StringIO()
        serve(self.repo, source, destination)
        results = [json.loads(line) for line in destination.getvalue().splitlines()]
        self.assertIn('error', results[0])
        self.assertEqual(results[1]['id'], 2)
        self.assertEqual(results[1]['result']['status'], 'ok')
        with self.assertRaises(ValueError):
            dispatch(self.repo, 'build', {})
        with self.assertRaises(ValueError):
            dispatch(self.repo, 'get', {'name': 'Block', 'include_optional': 'false'})
        with self.assertRaises(ValueError):
            dispatch(self.repo, 'get', {'name': 'Block', 'tree': 'wrong unused filter'})

    def test_literal_search_and_unknown_filters_cannot_mutate_database(self):
        before = self.repo.connection.execute('SELECT count(*) FROM entities').fetchone()[0]
        self.repo.search('"; DROP TABLE entities; --', limit=2)
        self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM entities').fetchone()[0], before)
        with self.assertRaises(sqlite3.OperationalError):
            self.repo.connection.execute("DELETE FROM entities")
        with self.assertRaises(ValueError):
            self.repo.list_entities(optional=False)
        with self.assertRaises(ValueError):
            self.repo.list_entities(limit=True)
        with self.assertRaisesRegex(ValueError, 'Unknown/unimplemented entity kind'):
            self.repo.list_entities(kind='equipment')

    def test_reviewed_expression_references_preserve_or_and_count_context(self):
        result = self.repo.get('Elite Trooper')
        references = [r for r in result['relationships'] if r['relation'] == 'prerequisite_reference']
        flurry = next(r for r in references if r['target_name'] == 'Flurry')
        self.assertTrue(any(part['operator'] == 'any' for part in flurry['logic_path']))
        self.assertEqual(flurry['review_status'], 'reviewed_expression_reference_not_flat_requirement')
        trees = [r for r in references if r['condition']['op'] == 'count_talents']
        self.assertEqual(len(trees), 4)
        self.assertTrue(all(len(r['condition']['trees']) == 4 and r['condition']['at_least'] == 1 for r in trees))

    def test_recorded_category_redirect_and_url_casing(self):
        result = self.repo.get('Armor')
        self.assertEqual(result['entity']['kind'], 'category')
        self.assertEqual(self.repo.get('Category:Weapons')['entity']['kind'], 'category')
        self.assertEqual(self.repo.get('https://swse.miraheze.org/wiki/force_storm')['status'], 'not_found')
        self.assertEqual(self.repo.get('https://swse.miraheze.org/wiki/Force_Storm')['status'], 'ambiguous')

    def test_all_thirty_class_expressions_execute_with_explicit_synthetic_facts(self):
        # Exercises every encoded operation; not an independent proof that the
        # synthetic character is legal or that the local source is published RAW.
        items = self.repo.list_entities(kind='prestige_class', reviewed_prerequisites=True, limit=100)['items']
        for item in items:
            entity = self.repo.get(item['entity_id'])['entity']
            character = {}

            def provide(node):
                op = node['op']
                if op == 'all':
                    for child in node['args']:
                        provide(child)
                elif op == 'any':
                    provide(node['args'][0])
                elif op == 'gte':
                    character[node['field']] = max(character.get(node['field'], 0), node['value'])
                elif op == 'equals':
                    character[node['field']] = node['value']
                elif op == 'fact':
                    character.setdefault('facts', {})[node['name']] = True
                elif op == 'has':
                    character.setdefault(node['field'], []).append(node['value'])
                elif op == 'count_talents':
                    selected = []
                    for tree in node['trees']:
                        selected.extend(self.repo.list_entities(kind='talent', tree=tree, limit=500)['items'])
                    character.setdefault('talents', []).extend(t['entity_id'] for t in selected[:node['at_least']])
                else:
                    self.fail(f'Unhandled synthetic operation: {op}')

            provide(entity['prerequisites_ast'])
            with self.subTest(entity=item['entity_id']):
                self.assertEqual(self.repo.check(item['entity_id'], character)['result'], 'met')

    def test_json_lines_recursion_and_invalid_id_do_not_kill_adapter(self):
        source = io.StringIO('[' * 2000 + ']' * 2000 + '\n' +
                             json.dumps({'id': {}, 'method': 'doctor'}) + '\n' +
                             json.dumps({'id': 'next', 'method': 'list', 'params': {'kind': 'heroic_class'}}) + '\n')
        destination = io.StringIO()
        serve(self.repo, source, destination)
        results = [json.loads(line) for line in destination.getvalue().splitlines()]
        self.assertIn('error', results[0])
        self.assertIsNone(results[1]['id'])
        self.assertEqual(results[2]['result']['total'], 5)

    def test_doctor_integrity_and_fk_checks(self):
        result = self.repo.doctor()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['sqlite_integrity'], 'ok')
        self.assertEqual(result['foreign_key_violations'], 0)
        self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM missing_targets').fetchone()[0], 2622)

    def test_cli_json_and_machine_schema_methods_agree(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['--database', str(self.database), 'get', 'Armored Defense'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'ok')
        from tools.swse.cli import METHOD_ARGS
        schema = json.loads((ROOT / 'tools/swse/agent_tools.json').read_text())
        self.assertEqual({tool['name'] for tool in schema['tools']}, set(METHOD_ARGS))


class SnapshotFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.source_db = Path(cls.temp.name) / 'source.sqlite3'
        build(ROOT, cls.source_db)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def copy_snapshot(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name in ('SWSE-Analysis', 'curation', 'tools', 'catalog'):
            shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('__pycache__', '*.tmp'))
        database = root / 'snapshot.sqlite3'
        shutil.copyfile(self.source_db, database)
        return root, database

    def test_changed_source_stales_queries_and_failed_build_preserves_db(self):
        root, database = self.copy_snapshot()
        before = sha256(database.read_bytes())
        file = root / 'SWSE-Analysis/swse_wiki_export/pages/swse-miraheze-org/rapid-strike.md'
        file.write_text(file.read_text().replace('two quick strikes', 'three quick strikes'))
        with self.assertRaisesRegex(ValueError, 'Stale retrieval index input'):
            Repository(root, database)
        with self.assertRaisesRegex(ValueError, 'hash/count mismatch'):
            build(root, database)
        self.assertEqual(sha256(database.read_bytes()), before)

    def test_changed_curation_stales_index_and_stale_review_hash_fails_build(self):
        root, database = self.copy_snapshot()
        file = root / 'curation/overrides.json'
        config = json.loads(file.read_text())
        config['documents']['force-storm']['article_sha256'] = '0' * 64
        file.write_text(json.dumps(config))
        before = sha256(database.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Stale retrieval index input'):
            Repository(root, database)
        with self.assertRaisesRegex(ValueError, 'Stale curated article hash'):
            build(root, database)
        self.assertEqual(sha256(database.read_bytes()), before)

    def test_new_unindexed_file_and_changed_tool_code_rejected(self):
        root, database = self.copy_snapshot()
        new = root / 'SWSE-Analysis/swse_wiki_export/pages/new.md'
        new.write_text('new data')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            Repository(root, database)
        new.unlink()
        tool = root / 'tools/swse/text.py'
        tool.write_text(tool.read_text() + '\n# Changed implementation\n')
        with self.assertRaisesRegex(ValueError, 'Stale retrieval index input'):
            Repository(root, database)

    def test_invalid_boundary_cannot_split_table_and_preserves_old_db(self):
        root, database = self.copy_snapshot()
        file = root / 'curation/overrides.json'
        config = json.loads(file.read_text())
        config['documents']['move-object']['annotations'][0]['range'][1] = 31
        file.write_text(json.dumps(config))
        before = sha256(database.read_bytes())
        with self.assertRaisesRegex(ValueError, 'split a Markdown table'):
            build(root, database)
        self.assertEqual(sha256(database.read_bytes()), before)

    def test_database_cannot_be_built_inside_archive(self):
        with self.assertRaisesRegex(ValueError, 'outside the source archive'):
            build(ROOT, ROOT / 'SWSE-Analysis/forbidden.sqlite3')

    def test_database_destination_cannot_clobber_code_git_or_foreign_data(self):
        for folder in ('.git', 'tools', 'curation', 'docs'):
            with self.subTest(folder=folder), self.assertRaisesRegex(ValueError, 'protected'):
                build(ROOT, ROOT / folder / 'forbidden.sqlite3')
        with self.assertRaisesRegex(ValueError, 'SQLite extension'):
            build(ROOT, ROOT / 'README.md')
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory) / 'foreign.sqlite3'
            with sqlite3.connect(foreign) as connection:
                connection.execute('CREATE TABLE private_data (value TEXT)')
            before = sha256(foreign.read_bytes())
            with self.assertRaisesRegex(ValueError, 'unrelated database'):
                build(ROOT, foreign)
            self.assertEqual(sha256(foreign.read_bytes()), before)
