#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `codemetrics` package."""

import datetime as dt
import io
import textwrap
import unittest
import unittest.mock as mock

import numpy as np
import pandas as pd
import lizard as lz

import codemetrics as cm
import codemetrics.scm as scm
from tests.utils import DataFrameTestCase


class SimpleRepositoryFixture(DataFrameTestCase):
    """Given a repository of a few records."""

    @staticmethod
    def get_log_df():
        csv_data = io.StringIO(textwrap.dedent('''
        revision,author,date,textmods,kind,action,propmods,path,message,added,removed
        1016,elmotec,2018-02-26T10:28:00Z,true,file,M,false,stats.py,modified again,1,2
        1018,elmotec,2018-02-24T11:14:11Z,true,file,M,false,stats.py,modified,3,4
        1018,elmotec,2018-02-24T11:14:11Z,true,file,M,false,requirements.txt,modified,5,6'''))
        date_parser = (lambda d: dt.datetime.strptime(d, '%Y-%m-%dT%H:%M:%SZ').
                       replace(tzinfo=dt.timezone.utc))
        df = pd.read_csv(csv_data, parse_dates=['date'],
                         date_parser=date_parser)
        return df

    @staticmethod
    def get_files_df():
        return pd.read_csv(io.StringIO(textwrap.dedent('''
        path
        stats.py
        requirements.txt
        ''')))

    @staticmethod
    def get_loc_df():
        return pd.read_csv(io.StringIO(textwrap.dedent('''
        language,path,blank,comment,code
        Python,stats.py,28,84,100
        Unknown,requirements.txt,0,0,3
        ''')))

    def setUp(self):
        super().setUp()
        self.log = self.get_log_df()
        self.loc = self.get_loc_df()
        self.files = self.get_files_df()


class GetMassChangesTestCase(SimpleRepositoryFixture):
    """Test non-report features."""

    def setUp(self):
        """Sets up tests"""
        super().setUp()
        self.log = SimpleRepositoryFixture.get_log_df()
        self.expected = pd.read_csv(
            io.StringIO(textwrap.dedent('''
            revision,path,changes,changes_per_path
            1016,1,3,3.0
            1018,2,18,9.0
            ''')))

    def test_get_mass_changes(self):
        """Retrieve mass changes easily."""
        actual = cm.get_mass_changes(self.log, min_path=2)
        self.assertEqual(self.expected.query("revision == '1018'"), actual)

    def test_get_no_mass_changes(self):
        """Handles case where no mass changes are found."""
        actual = cm.get_mass_changes(self.log, min_path=100)
        self.assertEqual((0, 4), actual.shape)

    def test_get_mass_changes_on_indexed_log(self):
        """The function works when the input log is indexed."""
        log = self.log.set_index(['revision', 'path'])
        actual = cm.get_mass_changes(log, min_path=2)
        self.assertEqual(self.expected.query("revision == '1018'"), actual)

    def test_get_mass_changes_on_changes_per_path(self):
        """Retrieve mass changes using changes_per_path."""
        actual = cm.get_mass_changes(self.log, max_changes_per_path=5.0)
        self.assertEqual(self.expected.query("revision == '1016'"), actual)


class AgeReportTestCase(SimpleRepositoryFixture):
    """Extends the repository scaffolding with an age report."""

    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2018, 2, 28, tzinfo=dt.timezone.utc)
        self.get_now_patcher = mock.patch('codemetrics.internals.get_now',
                                          autospec=True, return_value=self.now)
        self.get_now = self.get_now_patcher.start()
        self.expected = pd.DataFrame(data={'path': ['requirements.txt', 'stats.py'],
                                           'age': [3.531817, 1.563889]})

    def tearDown(self):
        self.get_now_patcher.stop()

    def test_ages(self):
        """The age report generates data based on the SCM log data"""
        actual = cm.get_ages(self.log)
        self.assertEqual(self.expected, actual)

    def test_ages_enriched_with_kind(self):
        """Allow to use additional columns in age report."""
        actual = cm.get_ages(self.log, by=['path', 'kind'])[['path', 'age', 'kind']]
        self.expected['kind'] = 'file'
        self.assertEqual(self.expected, actual)

    def test_key_parameter(self):
        """Ignore files_df if nothing in it is relevant"""
        self.log['component'] = 'kernel'
        actual = cm.get_ages(self.log, by=['component', 'kind'])
        expected = pd.read_csv(io.StringIO(textwrap.dedent('''
        component,kind,age
        kernel,file,1.563889''')))
        self.assertEqual(expected, actual)

    def test_ages_when_revision_in_index(self):
        """Handle when inpput has path in index."""
        actual = cm.get_ages(self.log.set_index(['revision', 'path']))
        self.assertEqual(self.expected, actual)


class HotSpotReportTestCase(SimpleRepositoryFixture):
    """Extends the repository scaffolding with a hot spot report."""

    def setUp(self):
        super().setUp()

    def test_hot_spot_report(self):
        """Generate a report to find hot spots."""
        after = dt.datetime(2018, 2, 26, tzinfo=dt.timezone.utc)
        log = self.log.loc[self.log['date'] >= after, :]
        actual = cm.get_hot_spots(log, self.loc)
        expected = pd.read_csv(io.StringIO(textwrap.dedent('''
        language,path,blank,comment,lines,changes
        Python,stats.py,28,84,100,1.0
        Unknown,requirements.txt,0,0,3,0
        ''')))
        self.assertEqual(expected, actual)

    def test_hot_spot_with_custom_change_metric(self):
        """Generate report with a different change metric than revision."""
        # force all rows to the same date.
        self.log['day'] = dt.datetime(2018, 2, 24, tzinfo=dt.timezone.utc)
        actual = cm.get_hot_spots(self.log, self.loc, count_one_change_per=['day'])
        expected = pd.read_csv(io.StringIO(textwrap.dedent('''
        language,path,blank,comment,lines,changes
        Python,stats.py,28,84,100,1
        Unknown,requirements.txt,0,0,3,1
        ''')))
        self.assertEqual(expected, actual)


class CoChangeTestCase(SimpleRepositoryFixture):
    """CoChangeReport test case."""

    def setUp(self):
        super().setUp()

    def test_co_change_report(self):
        """Simple CoChangeReport usage."""
        actual = cm.get_co_changes(log=SimpleRepositoryFixture.get_log_df())
        expected = pd.read_csv(io.StringIO(textwrap.dedent('''
        path,dependency,changes,cochanges,coupling
        requirements.txt,stats.py,1,1,1.0
        stats.py,requirements.txt,2,1,0.5
        ''')))
        self.assertEqual(expected, actual)

    def test_co_change_report_on_day(self):
        """Check handling of on with the date as a day in argument."""
        log = SimpleRepositoryFixture.get_log_df()
        # Same day to force results different from test_co_change_report.
        log['day'] = pd.to_datetime('2018-02-24')
        actual = cm.get_co_changes(log=log, on='day')
        expected = pd.read_csv(io.StringIO(textwrap.dedent('''
        path,dependency,changes,cochanges,coupling
        requirements.txt,stats.py,1,1,1.0
        stats.py,requirements.txt,1,1,1.0
        ''')))
        self.assertEqual(expected, actual)


code_maat_dataset = pd.read_csv(io.StringIO(textwrap.dedent(r'''
path,component
.\.travis.yml,
.\project.clj,
.\src\code_maat\analysis\authors.clj,analysis.src
.\src\code_maat\analysis\churn.clj,analysis.src
.\src\code_maat\analysis\code_age.clj,analysis.src
.\src\code_maat\analysis\commit_messages.clj,analysis.src
.\src\code_maat\analysis\communication.clj,analysis.src
.\src\code_maat\analysis\coupling_algos.clj,analysis.src
.\src\code_maat\analysis\effort.clj,analysis.src
.\src\code_maat\analysis\entities.clj,analysis.src
.\src\code_maat\analysis\logical_coupling.clj,analysis.src
.\src\code_maat\analysis\math.clj,analysis.src
.\src\code_maat\analysis\sum_of_coupling.clj,analysis.src
.\src\code_maat\analysis\summary.clj,analysis.src
.\src\code_maat\analysis\workarounds.clj,analysis.src
.\src\code_maat\app\app.clj,app.src
.\src\code_maat\app\grouper.clj,app.src
.\src\code_maat\app\team_mapper.clj,app.src
.\src\code_maat\app\time_based_grouper.clj,app.src
.\src\code_maat\cmd_line.clj,analysis.src
.\src\code_maat\dataset\dataset.clj,dataset
.\src\code_maat\output\csv.clj,output
.\src\code_maat\output\filters.clj,output
.\src\code_maat\parsers\git.clj,parsers.src
.\src\code_maat\parsers\git2.clj,parsers.src
.\src\code_maat\parsers\hiccup_based_parser.clj,parsers.src
.\src\code_maat\parsers\limitters.clj,parsers.src
.\src\code_maat\parsers\mercurial.clj,parsers.src
.\src\code_maat\parsers\perforce.clj,parsers.src
.\src\code_maat\parsers\svn.clj,parsers.src
.\src\code_maat\parsers\tfs.clj,parsers.src
.\src\code_maat\parsers\time_parser.clj,parsers.src
.\src\code_maat\parsers\xml.clj,parsers.src
.\test\code_maat\analysis\authors_test.clj,analysis.test
.\test\code_maat\analysis\churn_test.clj,analysis.test
.\test\code_maat\analysis\code_age_test.clj,analysis.test
.\test\code_maat\analysis\commit_messages_test.clj,analysis.test
.\test\code_maat\analysis\communication_test.clj,analysis.test
.\test\code_maat\analysis\coupling_algos_test.clj,analysis.test
.\test\code_maat\analysis\effort_test.clj,analysis.test
.\test\code_maat\analysis\entities_test.clj,analysis.test
.\test\code_maat\analysis\logical_coupling_test.clj,analysis.test
.\test\code_maat\analysis\math_test.clj,analysis.test
.\test\code_maat\analysis\sum_of_coupling_test.clj,analysis.test
.\test\code_maat\analysis\test_data.clj,analysis.test
.\test\code_maat\app\cmd_line_test.clj,app.test
.\test\code_maat\app\grouper_test.clj,app.test
.\test\code_maat\app\team_mapper_test.clj,app.test
.\test\code_maat\app\time_based_grouper_test.clj,app.test
.\test\code_maat\dataset\dataset_test.clj,dataset
.\test\code_maat\end_to_end\churn_scenario_test.clj,end_to_end.test
.\test\code_maat\end_to_end\empty.xml,end_to_end.test
.\test\code_maat\end_to_end\git_live_data_test.clj,end_to_end.test
.\test\code_maat\end_to_end\mercurial_live_data_test.clj,end_to_end.test
.\test\code_maat\end_to_end\perforce_live_data_test.clj,end_to_end.test
.\test\code_maat\end_to_end\scenario_tests.clj,end_to_end.test
.\test\code_maat\end_to_end\simple.xml,end_to_end.test
.\test\code_maat\end_to_end\svn_live_data_test.clj,end_to_end.test
.\test\code_maat\end_to_end\team_level_analyses_test.clj,end_to_end.test
.\test\code_maat\end_to_end\tfs_live_data_test.clj,end_to_end.test
.\test\code_maat\parsers\git_test.clj,parsers.test
.\test\code_maat\parsers\mercurial_test.clj,parsers.test
.\test\code_maat\parsers\perforce_test.clj,parsers.test
.\test\code_maat\parsers\svn_test.clj,parsers.test
.\test\code_maat\parsers\tfs_test.clj,parsers.test
.\test\code_maat\parsers\time_parser_test.clj,parsers.test
.\test\code_maat\tools\test_tools.clj,
'''))).fillna('')


class ComponentTestCase(SimpleRepositoryFixture):
    """Test guess_components function."""

    def setUp(self):
        """Given a list of paths."""
        super().setUp()
        self.paths = code_maat_dataset['path']
        # keeps random generated sequences consistent over runs.
        np.random.seed(0)

    def test_can_guess_components(self):
        """Cluster paths in components."""
        actual = cm.guess_components(self.paths, stop_words={'code_maat'},
                                     n_clusters=10)
        actual = actual.sort_values(by='path').reset_index(drop=True)
        expected = code_maat_dataset
        self.assertEqual(expected, actual)

    def test_guess_components_for_specific_n_clusters(self):
        """Cluster paths to a specific number of components"""
        n_clusters = 3
        comps = cm.guess_components(self.paths, stop_words={'code_maat'},
                                    n_clusters=n_clusters)
        actual = comps[['component']].drop_duplicates().reset_index(drop=True)
        expected = pd.DataFrame(data={'component': ['parsers', 'src.analysis', 'test']})
        self.assertEqual(expected, actual)


class GetComplexityTestCase(DataFrameTestCase):
    """Test complexity analysis."""

    file_content_1 = textwrap.dedent('''\
    def test():
        if not True:
            print('we should never get there!')
        print('all OK!')
    ''')

    file_content_2 = textwrap.dedent('''\
    def test():
        print('all OK!')
    
    def other():
        print('all good')
    ''')

    def setUp(self):
        super().setUp()
        self.log = pd.read_csv(io.StringIO(textwrap.dedent("""\
        revision,author,date,textmods,kind,action,propmods,path,message
        r1,elmotec,2018-02-26T10:28:00Z,true,file,M,false,f.py,again
        r2,elmotec,2018-02-24T11:14:11Z,true,file,M,false,f.py,modified""")))

    def get_complexity(self, download_func):
        """Factor retrieval of complexity"""
        df = self.log.groupby(['revision', 'path']).\
            apply(cm.get_complexity, download_func=download_func)
        return df

    @mock.patch('lizard.auto_read', autospec=True,
                return_value=file_content_1, create=True)
    def test_lizard_analyze(self, _):
        actuals = list(lz.analyze_files([__file__], exts=lz.get_extensions([])))
        self.assertEqual(len(actuals), 1)
        actual = actuals[0]
        self.assertEqual(4, actual.nloc)
        self.assertEqual(2.0, actual.average_cyclomatic_complexity)

    def test_handles_no_function(self):
        """Handles files with no function well."""
        file_name, rev = 'f.py', 1

        def scm_download_file(_):
            return cm.scm.DownloadResult(rev, file_name, '')

        actual = self.get_complexity(scm_download_file).\
            reset_index().\
            pipe(pd.Series.astype, 'str')
        columns = 'revision path function'.split() + \
                  cm.core._lizard_fields + \
                  'file_tokens file_nloc'.split()
        expected = pd.DataFrame(data={k: [] for k in columns}, dtype='object')
        self.assertEqual(expected, actual)

    @mock.patch('codemetrics.internals.run', autospec=True,
                side_effect=[file_content_1, file_content_2])
    def test_analysis_with_groupby_svn_download(self, run_):
        """Check interface with svn."""
        actual = self.get_complexity(cm.svn.download)
        expected_calls = [mock.call('svn cat -r r1 f.py'),
                          mock.call('svn cat -r r2 f.py')]
        self.assertEqual(expected_calls, run_.call_args_list)
        expected = pd.read_csv(io.StringIO(textwrap.dedent("""\
        revision,path,function,cyclomatic_complexity,nloc,token_count,name,long_name,start_line,end_line,top_nesting_level,length,fan_in,fan_out,general_fan_out,file_tokens,file_nloc
        r1,f.py,0,2,4,16,test,test( ),1,4,0,4,0,0,0,17,4
        r2,f.py,0,1,2,8,test,test( ),1,2,0,2,0,0,0,18,4
        r2,f.py,1,1,2,8,other,other( ),4,5,0,2,0,0,0,18,4
        """))).set_index(['revision', 'path', 'function'])
        self.assertEqual(expected, actual)

    @mock.patch('codemetrics.internals.run', autospec=True, return_value=None)
    def test_analysis_empty_input_return_empty_output(self, _):
        """Empty input returns and empty dataframe."""
        self.log = self.log.iloc[:0]
        actual = cm.get_complexity(self.log, download_func=cm.svn.download)
        self.assertTrue(actual.empty)

    def test_use_default_download(self):
        """When the default_download_func is defined, use it."""
        download_func = mock.Mock(spec=cm.git.download,
                                  return_value=scm.DownloadResult(1, '/', ''))
        scm._default_download_func = download_func
        _ = cm.get_complexity(self.log)
        download_func.assert_called_with(self.log)


if __name__ == '__main__':
    unittest.main()



