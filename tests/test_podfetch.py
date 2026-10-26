import importlib.util
import io
import json
import os
import random
import shutil
import tempfile
import time
import unittest
import xml.etree.ElementTree as xmlreader
from contextlib import redirect_stdout
from unittest import mock

# The script's name has a dash, so it can't be imported the usual way
scriptPath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pod-downloader.py')
spec = importlib.util.spec_from_file_location('podfetch', scriptPath)
podfetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(podfetch)


def makeFeed(items):
    # An RSS feed from (title, url, pubDate) tuples, newest first like real feeds; url None means no enclosure
    parts = ['<?xml version="1.0" encoding="UTF-8"?><rss><channel><title>Test</title>']
    for title, url, pubDate in items:
        parts.append('<item><title>{0}</title>'.format(title))
        if pubDate:
            parts.append('<pubDate>{0}</pubDate>'.format(pubDate))
        if url:
            parts.append('<enclosure url="{0}" type="audio/mpeg"/>'.format(url))
        parts.append('</item>')
    parts.append('</channel></rss>')
    return ''.join(parts).encode('utf-8')


class FakeResponse:
    # Enough of requests.Response for the script: feeds, streamed downloads and webhook posts
    def __init__(self, content=b'', status=200):
        self.content = content
        self.status_code = status
        self.ok = status < 400
        self.headers = {'Content-Length': str(len(content))}

    def raise_for_status(self):
        if not self.ok:
            raise podfetch.requests.HTTPError('HTTP {0}'.format(self.status_code))

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PodfetchTestCase(unittest.TestCase):
    def setUp(self):
        # Fresh settings and counts for every test, with .part files in a temporary folder
        self.tempDir = tempfile.mkdtemp()
        podfetch.applySettings({'temp-path': os.path.join(self.tempDir, 'parts')})
        podfetch.dryRun = False
        for key in podfetch.totals:
            podfetch.totals[key] = 0
        podfetch.downloadedNames.clear()
        podfetch.failedNames.clear()
        podfetch.wouldDownload.clear()
        podfetch.showTitles.clear()
        podfetch.activeDownloads.clear()
        podfetch.progressLength = 0
        podfetch.planNotes.clear()

    def tearDown(self):
        shutil.rmtree(self.tempDir, ignore_errors=True)

    def quietly(self, function, *args, **kwargs):
        # Run without printing to the test output
        with redirect_stdout(io.StringIO()):
            return function(*args, **kwargs)


class CleanNameTests(unittest.TestCase):
    # These names must not change: existing downloads are recognised by them

    def test_colon_removed(self):
        self.assertEqual(podfetch.cleanName('2.5 Admins 214: No VLANs', 150), '2.5 Admins 214 No VLANs')

    def test_windows_invalid_characters_removed(self):
        self.assertEqual(podfetch.cleanName('a<b>c"d/e\\f|g?h*i', 150), 'abcdefghi')

    def test_trailing_space_and_dots_dropped(self):
        self.assertEqual(podfetch.cleanName('567: The year of Small Models ', 150), '567 The year of Small Models')
        self.assertEqual(podfetch.cleanName('407: And the Answer is...', 150), '407 And the Answer is')

    def test_runs_of_spaces_collapsed(self):
        self.assertEqual(podfetch.cleanName('Episode 235: Atomic Neon Kool-Aid  | LUP 235', 150), 'Episode 235 Atomic Neon Kool-Aid LUP 235')

    def test_control_characters_become_spaces(self):
        self.assertEqual(podfetch.cleanName('Line\nbreak\tand tab', 150), 'Line break and tab')

    def test_reserved_windows_name(self):
        self.assertEqual(podfetch.cleanName('CON', 150), 'CON_')

    def test_curly_apostrophe_kept(self):
        self.assertEqual(podfetch.cleanName('546: What You\u2019re Missing about NixOS', 150), '546 What You\u2019re Missing about NixOS')

    def test_length_limit(self):
        self.assertEqual(len(podfetch.cleanName('x' * 300, 150)), 150)

    def test_byte_limit_for_multibyte_characters(self):
        name = podfetch.cleanName('\u65e5' * 200, 150)
        self.assertLessEqual(len(name.encode('utf-8')), podfetch.maxNameBytes)


class ExtensionTests(unittest.TestCase):
    def test_extension_from_url(self):
        self.assertEqual(podfetch.getExtension('2.5admins-322.mp3', 'audio/mpeg'), 'mp3')

    def test_extension_from_type_when_url_has_none(self):
        self.assertEqual(podfetch.getExtension('12345', 'audio/mpeg'), 'mp3')
        self.assertEqual(podfetch.getExtension('12345', 'audio/x-m4a'), 'm4a')

    def test_no_extension_when_unknown(self):
        self.assertEqual(podfetch.getExtension('12345', None), '')


class ReleaseTimeTests(unittest.TestCase):
    def test_rss_date(self):
        self.assertEqual(podfetch.getReleaseTime('Thu, 22 Oct 2026 16:52:31 +0000'), 1792687951.0)

    def test_missing_or_bad_date(self):
        self.assertIsNone(podfetch.getReleaseTime(None))
        self.assertIsNone(podfetch.getReleaseTime('not a date'))


class BuildEpisodesTests(PodfetchTestCase):
    def build(self, items, useTitle=1):
        root = xmlreader.fromstring(makeFeed(items))
        return self.quietly(podfetch.buildEpisodes, root, self.tempDir, useTitle)

    def test_title_names_oldest_first(self):
        episodes = self.build([
            ('2.5 Admins 215: Still no VLANs', 'https://x/2.5admins-215.mp3', None),
            ('2.5 Admins 214: No VLANs', 'https://x/2.5admins-214.mp3', None),
        ])
        self.assertEqual([e['filename'] for e in episodes], ['2.5 Admins 214 No VLANs.mp3', '2.5 Admins 215 Still no VLANs.mp3'])

    def test_url_names(self):
        episodes = self.build([('Ep', 'https://x/LMP92.mp3?source=rss', None)], useTitle=0)
        self.assertEqual(episodes[0]['filename'], 'LMP92.mp3')

    def test_repeated_titles_numbered_from_the_oldest(self):
        episodes = self.build([
            ('Bonus', 'https://x/c.mp3', None),
            ('bonus', 'https://x/b.mp3', None),
            ('Bonus', 'https://x/a.mp3', None),
        ])
        self.assertEqual([e['filename'] for e in episodes], ['Bonus.mp3', 'bonus (2).mp3', 'Bonus (3).mp3'])

    def test_item_without_audio_skipped(self):
        episodes = self.build([('Text post', None, None), ('Ep 1', 'https://x/1.mp3', None)])
        self.assertEqual([e['title'] for e in episodes], ['Ep 1'])


class SelectEpisodesTests(unittest.TestCase):
    episodes = [{'title': 'Ep {0}: Topic'.format(n), 'filename': 'Ep {0} Topic.mp3'.format(n)} for n in range(1, 6)]

    def test_skip_by_title_filename_or_name_without_extension(self):
        kept = podfetch.selectEpisodes(self.episodes, ['ep 1: topic', 'Ep 2 Topic.mp3', 'EP 3 TOPIC'], 0)
        self.assertEqual([e['title'] for e in kept], ['Ep 4: Topic', 'Ep 5: Topic'])

    def test_skip_needs_the_whole_title(self):
        self.assertEqual(len(podfetch.selectEpisodes(self.episodes, ['Ep 1'], 0)), 5)

    def test_max_episodes_keeps_newest_after_skipping(self):
        kept = podfetch.selectEpisodes(self.episodes, ['Ep 5: Topic'], 2)
        self.assertEqual([e['title'] for e in kept], ['Ep 3: Topic', 'Ep 4: Topic'])


class InactiveTests(unittest.TestCase):
    now = 1_800_000_000
    day = 24 * 60 * 60

    def test_old_show_is_inactive(self):
        self.assertTrue(podfetch.isInactive([{'releaseTime': self.now - 100 * self.day}], 90, self.now))

    def test_recent_show_is_active(self):
        episodes = [{'releaseTime': self.now - 400 * self.day}, {'releaseTime': self.now - 10 * self.day}]
        self.assertFalse(podfetch.isInactive(episodes, 90, self.now))

    def test_off_or_without_dates(self):
        self.assertFalse(podfetch.isInactive([{'releaseTime': self.now - 100 * self.day}], 0, self.now))
        self.assertFalse(podfetch.isInactive([{'releaseTime': None}], 90, self.now))


class ProgressTests(PodfetchTestCase):
    megabyte = 1024 * 1024

    def test_bar(self):
        self.assertEqual(podfetch.renderProgress(22 * self.megabyte, 44 * self.megabyte, 100),
                         '  [###############---------------]  50%  22.0 / 44.0 MB')

    def test_unknown_size(self):
        self.assertEqual(podfetch.renderProgress(5 * self.megabyte, 0, 100), '  5.0 MB')

    def test_bar_cut_to_fit(self):
        self.assertEqual(len(podfetch.renderProgress(self.megabyte, 2 * self.megabyte, 20)), 20)

    def test_messages_print_above_the_progress_line(self):
        podfetch.showProgress = True
        output = io.StringIO()
        with redirect_stdout(output), mock.patch.object(podfetch.shutil, 'get_terminal_size', return_value=os.terminal_size((80, 24))):
            podfetch.updateProgress('a', 'Ep A', self.megabyte, 2 * self.megabyte, force=True)
            podfetch.log('Downloading B')
            podfetch.finishProgress('a')
        text = output.getvalue()
        # Bar drawn, cleared for the message, drawn again below it, then cleared when finished
        bar = '  [###############---------------]  50%  1.0 / 2.0 MB'
        self.assertEqual(text, '\r' + bar + '\r' + ' ' * len(bar) + '\r' + 'Downloading B\n' + '\r' + bar + '\r' + ' ' * len(bar) + '\r')
        self.assertEqual(podfetch.activeDownloads, {})

    def test_progress_off_prints_nothing_extra(self):
        output = io.StringIO()
        with redirect_stdout(output):
            podfetch.updateProgress('a', 'Ep A', 1, 2, force=True)
            podfetch.log('Hello')
            podfetch.finishProgress('a')
        self.assertEqual(output.getvalue(), 'Hello\n')


class ColorTests(PodfetchTestCase):
    def tearDown(self):
        podfetch.useColor = False
        podfetch.logFile = None
        super().tearDown()

    def test_plain_when_off(self):
        self.assertEqual(podfetch.paint('✔', 'green'), '✔')

    def test_codes_when_on(self):
        podfetch.useColor = True
        self.assertEqual(podfetch.paint('✔', 'green'), '\033[32m✔\033[0m')
        self.assertEqual(podfetch.paint('x', 'bold', 'cyan'), '\033[1;36mx\033[0m')

    def test_log_file_never_gets_colour_codes(self):
        podfetch.useColor = True
        podfetch.logFile = os.path.join(self.tempDir, 'run.log')
        self.quietly(podfetch.log, podfetch.paint('✔', 'green') + ' done')
        with open(podfetch.logFile, encoding='utf-8') as f:
            self.assertTrue(f.read().endswith('  ✔ done\n'))

    def test_tree_columns_line_up_with_colour_on(self):
        podfetch.useColor = True
        lines = [podfetch.colorPattern.sub('', line) for line in podfetch.treeLines([('A', '9 ep', '1.0 MB', ''), ('Longer name', '10 ep', '12.0 MB', '')])]
        self.assertEqual(lines, ['  ├─ A             9 ep   1.0 MB', '  └─ Longer name  10 ep  12.0 MB'])

    def test_no_colour_outside_a_terminal(self):
        with mock.patch.object(podfetch.sys.stdout, 'isatty', return_value=False):
            self.assertFalse(podfetch.enableColor())
        with mock.patch.object(podfetch.sys.stdout, 'isatty', return_value=True), mock.patch.dict(os.environ, {'NO_COLOR': '1'}):
            self.assertFalse(podfetch.enableColor())


class MixedOrderTests(unittest.TestCase):
    queues = [['a1', 'a2', 'a3'], ['b1', 'b2'], [], ['c1']]

    def test_everything_once_and_each_show_in_order(self):
        for seed in range(20):
            rng = random.Random(seed)
            order = list(podfetch.mixedOrder(self.queues, pick=rng.choice))
            self.assertEqual(sorted(order), ['a1', 'a2', 'a3', 'b1', 'b2', 'c1'])
            for queue in self.queues:
                self.assertEqual([item for item in order if item in queue], queue)

    def test_shows_are_interleaved(self):
        # Always picking the last show with episodes left alternates between shows
        order = list(podfetch.mixedOrder(self.queues, pick=lambda queues: queues[-1]))
        self.assertEqual(order, ['c1', 'b1', 'b2', 'a1', 'a2', 'a3'])
        rng = random.Random(1)
        orders = {tuple(podfetch.mixedOrder(self.queues, pick=rng.choice)) for _ in range(20)}
        self.assertGreater(len(orders), 1, 'random picks give different orders')

    def test_input_lists_untouched(self):
        queues = [['a1'], ['b1']]
        list(podfetch.mixedOrder(queues))
        self.assertEqual(queues, [['a1'], ['b1']])


class LooseNameTests(unittest.TestCase):
    def test_garbled_apostrophe_matches_correct_name(self):
        self.assertEqual(podfetch.looseName('Episode 124 Linux\u00e2\u20ac\u2122s Amazing Year LUP 124.mp3'),
                         podfetch.looseName('Episode 124 Linux\u2019s Amazing Year LUP 124.mp3'))

    def test_trailing_space_and_double_space_match(self):
        self.assertEqual(podfetch.looseName('567 The year of Small Models .mp3'), podfetch.looseName('567 The year of Small Models.mp3'))
        self.assertEqual(podfetch.looseName('Ep 23 Nest  LUP 23.mp3'), podfetch.looseName('Ep 23 Nest LUP 23.mp3'))


class ThrottleTests(unittest.TestCase):
    def test_pause_when_ahead_of_the_limit(self):
        # 2 MB in 1 second at a 1 MB/s limit: wait 1 more second
        self.assertAlmostEqual(podfetch.throttleDelay(2 * 1024 * 1024, 1.0, 1024 * 1024), 1.0)

    def test_no_pause_when_under_the_limit(self):
        self.assertEqual(podfetch.throttleDelay(512 * 1024, 1.0, 1024 * 1024), 0.0)


class NotifyTests(PodfetchTestCase):
    def test_payload_formats(self):
        self.assertEqual(podfetch.notifyPayload('slack', 'hi'), {'text': 'hi'})
        self.assertEqual(podfetch.notifyPayload('discord', 'hi'), {'content': 'hi', 'username': 'podfetch'})
        self.assertEqual(podfetch.notifyPayload('voidy', 'hi'), {'content': 'hi', 'username': 'podfetch'})

    def test_message_lists_episodes_and_failures(self):
        podfetch.totals.update(downloaded=1, failed=1)
        podfetch.downloadedNames.append(('2.5admins', '2.5 Admins 323 Something.mp3', 51275366))
        podfetch.failedNames.append(('coder raido', '660 Broken.mp3'))
        message = podfetch.buildNotifyMessage(2000)
        self.assertEqual(message, 'podfetch: 1 new episode (48.9 MB), 1 failed\n'
                                  '• 2.5admins: 2.5 Admins 323 Something (48.9 MB)\n'
                                  'Failed:\n'
                                  '• coder raido: 660 Broken')

    def test_message_cut_to_the_limit(self):
        podfetch.totals['downloaded'] = 500
        podfetch.downloadedNames.extend(('show', 'Episode {0} with a fairly long title.mp3'.format(n), 40 * 1024 ** 2) for n in range(500))
        message = podfetch.buildNotifyMessage(2000)
        self.assertLessEqual(len(message), 2000)
        self.assertRegex(message, r'\.\.\. and \d+ more$')
        self.assertTrue(message.startswith('podfetch: 500 new episodes (19.5 GB)'), 'the total covers every episode, not just the listed ones')

    def test_summary_all_downloaded(self):
        podfetch.showTitles.update({'2.5admins': '2.5 Admins', 'coder raido': 'Coder Radio'})
        podfetch.totals['downloaded'] = 10
        podfetch.downloadedNames.extend(('2.5admins', 'ep{0}.mp3'.format(n), 3 * 1024 ** 2) for n in range(9))
        podfetch.downloadedNames.append(('coder raido', '660.mp3', 3 * 1024 ** 2))
        self.assertEqual(podfetch.summaryLines(), [
            '✔ 10 of 10 downloaded · 30.0 MB',
            '  ├─ 2.5 Admins   9 ep  27.0 MB',
            '  └─ Coder Radio  1 ep   3.0 MB',
        ])

    def test_summary_with_failures(self):
        podfetch.showTitles.update({'2.5admins': '2.5 Admins'})
        podfetch.totals.update(downloaded=1, failed=2, failedShows=1)
        podfetch.downloadedNames.append(('2.5admins', 'a.mp3', 30 * 1024 ** 2))
        podfetch.failedNames.extend([('2.5admins', 'b.mp3'), ('coder raido', 'c.mp3')])
        self.assertEqual(podfetch.summaryLines(), [
            '⚠ 1 of 3 downloaded · 30.0 MB · 2 failed · 1 show could not be read',
            '  ├─ 2.5 Admins   1 ep  30.0 MB  ✖ 1 failed',
            '  └─ coder raido  0 ep   0.0 MB  ✖ 1 failed',
        ])

    def test_summary_nothing_new(self):
        self.assertEqual(podfetch.summaryLines(), ['✔ Nothing new'])

    def test_format_size(self):
        self.assertEqual(podfetch.formatSize(0), '0.0 MB')
        self.assertEqual(podfetch.formatSize(51275366), '48.9 MB')
        self.assertEqual(podfetch.formatSize(3 * 1024 ** 3), '3.0 GB')

    def test_notify_when(self):
        targets = [{'type': 'discord', 'url': 'https://discord.test/hook'}]
        with mock.patch.object(podfetch.requests, 'post', return_value=FakeResponse(status=204)) as post:
            podfetch.sendNotifications(targets, 'changes')
            self.assertFalse(post.called, 'nothing happened, so "changes" sends nothing')
            podfetch.sendNotifications(targets, 'always')
            self.assertEqual(post.call_count, 1)
            podfetch.totals['downloaded'] = 1
            podfetch.sendNotifications(targets, 'failures')
            self.assertEqual(post.call_count, 1, '"failures" ignores a run without failures')
            podfetch.sendNotifications(targets, 'changes')
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.kwargs['json']['username'], 'podfetch')
            self.assertEqual(post.call_args.kwargs['headers'], {})

    def test_voidy_bot_token_sent_as_header(self):
        podfetch.totals['downloaded'] = 1
        targets = [{'type': 'voidy', 'url': 'https://voidy.test/api/bot/rooms/3/messages', 'token': 'vbot_secret'}]
        with mock.patch.object(podfetch.requests, 'post', return_value=FakeResponse(status=201)) as post:
            podfetch.sendNotifications(targets, 'changes')
        self.assertEqual(post.call_args.kwargs['headers'], {'Authorization': 'Bot vbot_secret'})
        self.assertEqual(post.call_args.args[0], 'https://voidy.test/api/bot/rooms/3/messages')


class ConfigTests(PodfetchTestCase):
    def writeConfig(self, text):
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text if isinstance(text, str) else json.dumps(text))
        return path

    def configError(self, config):
        with self.assertRaises(SystemExit) as raised:
            self.quietly(podfetch.loadConfig, self.writeConfig(config))
        return str(raised.exception.code)

    def test_missing_file(self):
        with self.assertRaises(SystemExit) as raised:
            podfetch.loadConfig(os.path.join(self.tempDir, 'config.json'))
        self.assertIn('Copy config.json.example', str(raised.exception.code))

    def test_broken_json_gives_line_and_column(self):
        self.assertIn('line 1, column', self.configError('{"shows": [}'))

    def test_wrong_type_and_missing_setting(self):
        error = self.configError({'timeout': '60', 'shows': [{'url': 'x', 'title-as-filename': 1}]})
        self.assertIn('"timeout" at the top of config.json should be a number', error)
        self.assertIn('"folder" is missing in show 1', error)

    def test_bad_notify_and_skip_episodes(self):
        error = self.configError({'notify': [{'type': 'teams', 'url': 'x'}], 'notify-when': 'sometimes',
                                  'podcast-folder': 'Z:/', 'shows': [{'url': 'x', 'folder': 'y', 'title-as-filename': 1, 'skip-episodes': [1]}]})
        self.assertIn('notify entry 1 needs a "type"', error)
        self.assertIn('"parallel" must be at least 1', self.configError({'parallel': 0, 'shows': []}))
        self.assertIn('"notify-when" should be one of', error)
        self.assertIn('"skip-episodes" in show 1', error)

    def test_folder_joins_the_top_level_download_path(self):
        output = io.StringIO()
        with redirect_stdout(output):
            config = podfetch.loadConfig(self.writeConfig({
                'podcast-folder': 'Z:/', 'shows': [
                    {'url': 'https://x/a', 'folder': '2.5admins', 'title-as-filename': 1},
                    {'url': 'https://x/b', 'folder': 'other', 'download-path': 'D:/elsewhere', 'title-as-filename': 1},
                ]}))
        self.assertEqual(config['shows'][0]['download-path'], os.path.join('Z:/', '2.5admins'))
        self.assertEqual(podfetch.showName(config['shows'][0]), '2.5admins')
        self.assertEqual(config['shows'][1]['download-path'], os.path.join('Z:/', 'other'), "a show's own download-path is ignored")
        self.assertIn('unknown setting "download-path" in show 2 is ignored', output.getvalue())

    def test_folder_needs_a_download_path(self):
        error = self.configError({'shows': [{'url': 'x', 'folder': 'a', 'title-as-filename': 1},
                                            {'url': 'x', 'title-as-filename': 1}]})
        self.assertIn('"folder" in show 1 needs "podcast-folder" at the top', error)
        self.assertIn('"folder" is missing in show 2', error)

    def test_old_top_level_download_path_name_still_works(self):
        output = io.StringIO()
        with redirect_stdout(output):
            config = podfetch.loadConfig(self.writeConfig({'download-path': 'Z:/', 'shows': [
                {'url': 'https://x/feed', 'folder': 'a', 'title-as-filename': 1}]}))
        self.assertEqual(config['shows'][0]['download-path'], os.path.join('Z:/', 'a'))
        self.assertNotIn('unknown setting', output.getvalue())

    def test_old_show_url_name_still_works(self):
        output = io.StringIO()
        with redirect_stdout(output):
            config = podfetch.loadConfig(self.writeConfig({'podcast-folder': 'Z:/', 'shows': [
                {'show-url': 'https://x/feed', 'folder': 'y', 'title-as-filename': 1}]}))
        self.assertEqual(config['shows'][0]['url'], 'https://x/feed')
        self.assertNotIn('unknown setting', output.getvalue())

    def test_unknown_setting_only_warns(self):
        output = io.StringIO()
        with redirect_stdout(output):
            podfetch.loadConfig(self.writeConfig({'hide-skiped': 1, 'shows': []}))
        self.assertIn('unknown setting "hide-skiped"', output.getvalue())


class PickShowsTests(unittest.TestCase):
    shows = [
        {'url': 'https://2.5admins.com/feed/podcast/', 'download-path': 'Z:/2.5admins'},
        {'url': 'https://linuxunplugged.com/rss', 'download-path': 'Z:/linux unplugged', 'enabled': 0},
        {'url': 'https://latenightlinux.com/feed/mp3', 'download-path': 'Z:/late night linux'},
    ]

    def test_without_names_only_enabled_shows(self):
        self.assertEqual([podfetch.showName(s) for s in podfetch.pickShows(self.shows, None)], ['2.5admins', 'late night linux'])

    def test_by_exact_or_partial_name_including_disabled(self):
        self.assertEqual([podfetch.showName(s) for s in podfetch.pickShows(self.shows, ['unplugged'])], ['linux unplugged'])
        self.assertEqual([podfetch.showName(s) for s in podfetch.pickShows(self.shows, ['2.5ADMINS'])], ['2.5admins'])

    def test_unknown_name(self):
        with self.assertRaises(SystemExit):
            podfetch.pickShows(self.shows, ['nope'])


class RunTests(PodfetchTestCase):
    # Whole runs through main(), with the network faked

    def setUp(self):
        super().setUp()
        self.downloadDir = os.path.join(self.tempDir, 'episodes')
        now = time.time()
        self.feed = makeFeed([
            ('Ep 2: Newer', 'https://x/2.mp3', time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime(now - 86400))),
            ('Ep 1: Older', 'https://x/1.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000'),
        ])

    def fakeGet(self, url, **kwargs):
        if url == 'https://x/feed':
            return FakeResponse(self.feed)
        return FakeResponse(b'ID3 audio for ' + url.encode())

    def run_main(self, config, *arguments):
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        with mock.patch.object(podfetch.requests, 'get', side_effect=self.fakeGet):
            return self.quietly(podfetch.main, ['--config', path, *arguments])

    def config(self, **show):
        return {'temp-path': os.path.join(self.tempDir, 'parts'),
                'podcast-folder': self.tempDir,
                'shows': [{'url': 'https://x/feed', 'folder': 'episodes', 'title-as-filename': 1, **show}]}

    def test_download_names_and_dates_files(self):
        self.assertEqual(self.run_main(self.config()), 0)
        self.assertEqual(sorted(os.listdir(self.downloadDir)), ['Ep 1 Older.mp3', 'Ep 2 Newer.mp3'])
        self.assertEqual(os.path.getmtime(os.path.join(self.downloadDir, 'Ep 1 Older.mp3')),
                         podfetch.getReleaseTime('Thu, 01 Jan 2026 12:00:00 +0000'))
        self.assertEqual(os.listdir(os.path.join(self.tempDir, 'parts')), [], 'no .part files left behind')

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_main(self.config(), '--dry-run'), 0)
        self.assertFalse(os.path.exists(self.downloadDir))
        self.assertEqual(podfetch.totals['downloaded'], 2)
        self.assertEqual(podfetch.summaryLines(), ['◌ Dry run: would download 2', '  └─ Test  2 ep'])

    def test_summary_lists_shows_below_the_totals(self):
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.config(), f)
        output = io.StringIO()
        with mock.patch.object(podfetch.requests, 'get', side_effect=self.fakeGet), redirect_stdout(output):
            podfetch.main(['--config', path])
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-2:], ['✔ 2 of 2 downloaded · 0.0 MB', '  └─ Test  2 ep  0.0 MB'],
                         'the show is named by its feed title, "Test"')
        self.assertEqual(lines[:4], ['', '⇣ 2 episodes to download', '  └─ Test  2 ep', ''], 'the overview comes before the downloads')
        self.assertIn('[1/2 · 1 left] Test › Ep 2 Newer.mp3', lines)
        self.assertIn('[2/2 · 0 left] Test › Ep 1 Older.mp3', lines)
        self.assertFalse(any('https://x/' in line for line in lines), 'download URLs only appear with debug')

    def test_parallel_downloads_everything(self):
        output = self.run_text(json.dumps({**self.config(), 'parallel': 2}))
        self.assertEqual(sorted(os.listdir(self.downloadDir)), ['Ep 1 Older.mp3', 'Ep 2 Newer.mp3'])
        self.assertEqual(os.listdir(os.path.join(self.tempDir, 'parts')), [], 'no .part files left behind')
        self.assertIn('               ✔ Test › Ep 2 Newer.mp3 · 0.0 MB', output.splitlines(), 'finished lines line up under the counter')
        self.assertNotIn('no new episode', output, 'notes from other runs never carry over')
        self.assertIn('✔ 2 of 2 downloaded · 0.0 MB', output)

    def test_parallel_same_filename_in_two_shows(self):
        # Two shows each with an "Episode 1": downloaded at the same time, each must get its own file
        otherDir = os.path.join(self.tempDir, 'other')
        feeds = {'https://x/a': makeFeed([('Episode 1', 'https://x/a1.mp3', None)]),
                 'https://x/b': makeFeed([('Episode 1', 'https://x/b1.mp3', None)])}
        def get(url, **kwargs):
            if url in feeds:
                return FakeResponse(feeds[url])
            time.sleep(0.05)
            return FakeResponse(b'ID3 audio for ' + url.encode() + b' ' * 300000)
        config = {'temp-path': os.path.join(self.tempDir, 'parts'), 'parallel': 2, 'podcast-folder': self.tempDir, 'shows': [
            {'url': 'https://x/a', 'folder': 'episodes', 'title-as-filename': 1},
            {'url': 'https://x/b', 'folder': 'other', 'title-as-filename': 1}]}
        path = self.writeConfigText(json.dumps(config))
        with mock.patch.object(podfetch.requests, 'get', side_effect=get):
            self.assertEqual(self.quietly(podfetch.main, ['--config', path]), 0)
        with open(os.path.join(self.downloadDir, 'Episode 1.mp3'), 'rb') as f:
            self.assertTrue(f.read().startswith(b'ID3 audio for https://x/a1.mp3'))
        with open(os.path.join(otherDir, 'Episode 1.mp3'), 'rb') as f:
            self.assertTrue(f.read().startswith(b'ID3 audio for https://x/b1.mp3'))

    def test_stop_leaves_no_file_and_counts_nothing(self):
        podfetch.stopEvent.set()
        try:
            filepath = os.path.join(self.tempDir, 'Ep.mp3')
            with mock.patch.object(podfetch.requests, 'get', side_effect=self.fakeGet):
                self.assertIsNone(podfetch.downloadEpisode('https://x/1.mp3', 'Ep.mp3', filepath, None))
                self.quietly(podfetch.downloadPlanned, {'show': 'episodes', 'filepath': filepath,
                             'episode': {'filename': 'Ep.mp3', 'url': 'https://x/1.mp3', 'releaseTime': None}}, 1, 1)
            self.assertFalse(os.path.exists(filepath))
            self.assertEqual((podfetch.totals['downloaded'], podfetch.totals['failed']), (0, 0))
        finally:
            podfetch.stopEvent.clear()

    def test_parallel_turns_off_the_progress_bar(self):
        with mock.patch.object(podfetch.sys.stdout, 'isatty', return_value=True):
            podfetch.applySettings({'show-progressbar': 1})
            self.assertTrue(podfetch.showProgress)
            podfetch.applySettings({'show-progressbar': 1, 'parallel': 2})
            self.assertFalse(podfetch.showProgress)
        podfetch.applySettings({})

    def test_warning_first_when_progress_bar_and_parallel_are_both_on(self):
        output = self.run_text(json.dumps({**self.config(), 'show-progressbar': 1, 'parallel': 2}))
        self.assertEqual(output.splitlines()[0], '⚠ No progress bar while "parallel" is 2 · set "show-progressbar": 0 to hide this')
        self.assertNotIn('Warning', self.run_text(json.dumps({**self.config(), 'show-progressbar': 1})))
        self.assertNotIn('Warning', self.run_text(json.dumps({**self.config(), 'parallel': 2})))

    def test_debug_shows_where_episodes_come_from(self):
        output = self.run_text(json.dumps({**self.config(), 'debug': 1}))
        self.assertIn('  [debug] Reading feed https://x/feed', output)
        self.assertIn('  [debug] From https://x/2.mp3', output)
        self.assertIn('  [debug] Saving to ' + os.path.join(self.downloadDir, 'Ep 2 Newer.mp3'), output)

    def test_debug_flag(self):
        shutil.rmtree(self.downloadDir, ignore_errors=True)
        self.assertIn('[debug] From https://x/1.mp3', self.run_text(json.dumps(self.config()), '--debug'))

    def test_debug_never_shows_notification_urls(self):
        config = {**self.config(), 'debug': 1, 'notify': [{'type': 'discord', 'url': 'https://discord.test/api/webhooks/1/secret'}]}
        with mock.patch.object(podfetch.requests, 'post', return_value=FakeResponse(status=204)):
            output = self.run_text(json.dumps(config))
        self.assertIn('[debug] Sent discord notification: HTTP 204', output)
        self.assertNotIn('secret', output)

    def test_skip_episodes(self):
        self.run_main(self.config(**{'skip-episodes': ['Ep 1: Older']}))
        self.assertEqual(os.listdir(self.downloadDir), ['Ep 2 Newer.mp3'])

    def writeConfigText(self, text):
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return path

    def run_text(self, text, *arguments):
        # Run main() with config.json written exactly as given, and return its output
        path = self.writeConfigText(text)
        output = io.StringIO()
        with mock.patch.object(podfetch.requests, 'get', side_effect=self.fakeGet), redirect_stdout(output):
            podfetch.main(['--config', path, *arguments])
        return output.getvalue()

    def inactiveConfigText(self, enabled=', "enabled": 1'):
        # Hand-written layout, to check that disabling a show leaves the rest of the file as it was
        return ('{\n'
                '  "skip-inactive-days": 90,\n'
                '  "temp-path": ' + json.dumps(os.path.join(self.tempDir, 'parts')) + ',\n'
                '  "podcast-folder": ' + json.dumps(self.tempDir) + ',\n'
                '  "shows": [\n'
                '    {"url": "https://x/feed", "folder": "episodes", "title-as-filename": 1' + enabled + '},\n'
                '    {"url": "https://x/other", "folder": "unused", "title-as-filename": 1, "enabled": 0}\n'
                '  ]\n'
                '}\n')

    def test_inactive_show_with_missing_episodes_still_downloads_them(self):
        self.feed = makeFeed([('Old', 'https://x/old.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000')])
        text = self.inactiveConfigText()
        output = self.run_text(text)
        self.assertEqual(os.listdir(self.downloadDir), ['Old.mp3'])
        self.assertIn('  └─ Test  1 ep    · no new episode since 2026-01-01', output, 'the overview says why an ended show still downloads')
        with open(os.path.join(self.tempDir, 'config.json'), encoding='utf-8') as f:
            self.assertEqual(f.read(), text, 'not disabled while an episode was missing')

    def test_complete_inactive_show_is_disabled_in_config(self):
        self.feed = makeFeed([('Old', 'https://x/old.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000')])
        os.makedirs(self.downloadDir)
        open(os.path.join(self.downloadDir, 'Old.mp3'), 'wb').close()
        text = self.inactiveConfigText()
        output = self.run_text(text)
        self.assertIn('Disabling Test: all 1 episodes downloaded', output)
        with open(os.path.join(self.tempDir, 'config.json'), encoding='utf-8') as f:
            disabledText = f.read()
        self.assertEqual(disabledText, text.replace('"title-as-filename": 1, "enabled": 1}', '"title-as-filename": 1, "enabled": 0}'),
                         'only that show\'s "enabled" changed; the rest of the file is untouched')
        self.assertIn('Disabled: episodes', self.run_text(disabledText))

    def test_disabling_adds_enabled_when_missing(self):
        self.feed = makeFeed([('Old', 'https://x/old.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000')])
        os.makedirs(self.downloadDir)
        open(os.path.join(self.downloadDir, 'Old.mp3'), 'wb').close()
        self.run_text(self.inactiveConfigText(enabled=''))
        with open(os.path.join(self.tempDir, 'config.json'), encoding='utf-8') as f:
            config = json.load(f)
        self.assertEqual(config['shows'][0]['enabled'], 0)
        self.assertEqual(config['shows'][1], {'url': 'https://x/other', 'folder': 'unused', 'title-as-filename': 1, 'enabled': 0})

    def test_dry_run_only_says_it_would_disable(self):
        self.feed = makeFeed([('Old', 'https://x/old.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000')])
        os.makedirs(self.downloadDir)
        open(os.path.join(self.downloadDir, 'Old.mp3'), 'wb').close()
        text = self.inactiveConfigText()
        self.assertIn('Would disable Test', self.run_text(text, '--dry-run'))
        with open(os.path.join(self.tempDir, 'config.json'), encoding='utf-8') as f:
            self.assertEqual(f.read(), text)

    def test_inactive_show_picked_with_show_runs_normally(self):
        self.feed = makeFeed([('Old', 'https://x/old.mp3', 'Thu, 01 Jan 2026 12:00:00 +0000')])
        os.makedirs(self.downloadDir)
        open(os.path.join(self.downloadDir, 'Old.mp3'), 'wb').close()
        text = self.inactiveConfigText()
        output = self.run_text(text, '--show', 'episodes')
        self.assertNotIn('Disabling', output)
        with open(os.path.join(self.tempDir, 'config.json'), encoding='utf-8') as f:
            self.assertEqual(f.read(), text)

    def test_random_show_downloads_every_show(self):
        otherDir = os.path.join(self.tempDir, 'other')
        config = self.config()
        config['random-show'] = 1
        config['shows'].append({'url': 'https://x/feed', 'folder': 'other', 'title-as-filename': 1})
        self.assertEqual(self.run_main(config), 0)
        self.assertEqual(sorted(os.listdir(self.downloadDir)), ['Ep 1 Older.mp3', 'Ep 2 Newer.mp3'])
        self.assertEqual(sorted(os.listdir(otherDir)), ['Ep 1 Older.mp3', 'Ep 2 Newer.mp3'])

    def test_failed_download_sets_exit_code(self):
        def get(url, **kwargs):
            return FakeResponse(self.feed) if url == 'https://x/feed' else FakeResponse(status=404)
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.config(), f)
        with mock.patch.object(podfetch.requests, 'get', side_effect=get):
            self.assertEqual(self.quietly(podfetch.main, ['--config', path]), 1)

    def test_check_reports_misnamed_duplicate_and_extra_files(self):
        os.makedirs(self.downloadDir)
        for name in ['Ep 1 Older .mp3', 'Ep 2 Newer.mp3', 'Ep 2  Newer.mp3', 'Bonus.mp3']:
            open(os.path.join(self.downloadDir, name), 'wb').close()
        path = os.path.join(self.tempDir, 'config.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.config(), f)
        with mock.patch.object(podfetch.requests, 'get', side_effect=self.fakeGet):
            # loadConfig normally works out the show's full path from podcast-folder + folder
            report = self.quietly(podfetch.checkShow, {**self.config()['shows'][0], 'download-path': self.downloadDir})
        self.assertEqual(report['misnamed'], [('Ep 1 Older .mp3', 'Ep 1 Older.mp3')])
        self.assertEqual(report['duplicates'], [('Ep 2  Newer.mp3', 'Ep 2 Newer.mp3')])
        self.assertEqual(report['notInFeed'], ['Bonus.mp3'])
        self.assertEqual(report['missing'], ['Ep 1 Older.mp3'])


if __name__ == '__main__':
    unittest.main()
