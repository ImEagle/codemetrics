#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

import pandas as pd
import sklearn
import sklearn.feature_extraction.text

from . import internals

__all__ = [
    'get_mass_changesets',
    'ages',
    'hot_spots',
    'co_changes',
    'guess_components'
]

def get_mass_changesets(log, min_changes):
    """Extract mass change sets from the SCM log dataframe.

    Calculate the number of files changed by each revision and extract that
    list according to the threshold.

    Args:
        log: SCM log data.
        min_changes: threshold of changes above which a revision is included in the output.

    Returns:
        revisions that had more files changed than the threshold.

    """
    by_rev = log[['revision', 'path']].groupby('revision').count()
    by_rev.rename(columns={'path': 'path_count'}, inplace=True)
    by_rev.reset_index(inplace=True)
    massive = pd.merge(by_rev[by_rev['path_count'] > min_changes],
                       log[['revision', 'message', 'author']].drop_duplicates())
    return massive


def ages(log: pd.DataFrame, keys: str=None, utc: bool=None, **kwargs) -> pd.DataFrame:
    """Generate age series from date series.

    Takes the output of a SCM log or just the date column and retrun the series
    of ages.

    Args:
        log: log or date column of log.
        keys: keys when grouping data before calculating the age.
        utc: treat pandas.datetime as utc (defaults to True).

    Returns:
        age of most recent modification.

    Example::

        ages = codemetrics.ages(log_df)

    """
    if utc is None:
        utc = True
    if keys is None:
        excluded = {'revision', 'author', 'date', 'textmods',
                    'action', 'propmods', 'message'}
        keys = [col for col in log.columns if col not in excluded]
    now = internals.get_now()
    rv = log[keys + ['date']].groupby(keys).max().reset_index()
    rv['age'] = (now - pd.to_datetime(rv['date'], utc=utc))
    rv['age'] /= pd.Timedelta(1, unit='D')
    return rv.drop(columns=['date'])


def hot_spots(log, loc, by=None, count_one_change_per=None):
    """Generate hot spots from SCM and loc data.

    Cross SCM log and loc as an approximation of complexity to determine paths
    that are complex and change often.

    Args:
        log: output log from SCM.
        loc: output from cloc.
        by: aggregation level can be path (default), another column.
        count_one_change_per: allows one to count one change by day or one
                              change per JIRA instead of one change by revision.

    Returns:
        pandas.DataFrame

    """

    def compute_score(input_df):
        """Compute score on the input dataframe for ranking.

        Scale each column accoding to min/max policy and compute a score
        between 0 and 1 based on the product of each column scaled value.

        Args:
            input_df: data frame containing input.

        Returns:
            pandas.DataFrame

        """
        df = input_df.astype('float').copy()
        df.fillna(0.0, inplace=True)
        df -= df.min(axis=0)
        df /= df.max(axis=0)
        df.fillna(0.0, inplace=True)
        df = df ** 2
        return df

    if by is None:
        by = 'path'
    if count_one_change_per is None:
        count_one_change_per = ['revision']
    c_df = loc.copy()
    c_df = c_df.rename(columns={'code': 'complexity'})
    columns = count_one_change_per + [by]
    ch_df = log[columns].drop_duplicates()[by]. \
        value_counts().to_frame('changes')
    df = pd.merge(c_df, ch_df, right_index=True, left_on=by, how='outer'). \
        fillna(0.0)
    df[['complexity_score', 'changes_score']] = \
        compute_score(df[['complexity', 'changes']])
    df['score'] = df[['complexity_score', 'changes_score']].sum(axis=1)
    return df


def co_changes(log=None, by=None, on=None):
    """Generate co-changes report.

    Returns a DataFrame with the following columns:
    - primary: first path changed.
    - secondary: second path changed.
    - coupling: how often do the path change together.

    Args:
        log: output log from SCM.
        by: aggregation level. Defaults to path.
        on: Field name to join/merge on. Defaults to revision.

    Returns:
        pandas.DataFrame

    """
    if by is None:
        by = 'path'
    if on is None:
        on = 'revision'
    df = log[[on, by]].drop_duplicates()
    sj = pd.merge(df, df, on=on)
    sj = sj.rename(columns={by + '_x': 'primary', by + '_y': 'secondary'})
    sj.drop_duplicates(inplace=True)  # FIXME: needs a test
    sj = sj.groupby(['primary', 'secondary']).count().reset_index()
    result = pd.merge(sj[sj['primary'] == sj['secondary']][['primary', on]],
                      sj[sj['primary'] != sj['secondary']],
                      on='primary', suffixes=['_changes', '_cochanges'])
    result['coupling'] = result[on + '_cochanges'] / result[on + '_changes']
    return result[['primary', 'secondary', on + '_cochanges',
                   on + '_changes', 'coupling']]. \
        sort_values(by='coupling', ascending=False)


def guess_components(paths, stop_words=None, n_clusters=8):
    """Guess components from an iterable of paths.

    Args:
        paths: list of string containing file paths in the project.
        stop_words: stop words. Passed to TfidfVectorizer.
        n_clusters: number of clusters. Passed to MiniBatchKMeans.

    Returns:
        pandas.DataFrame

    See Also:
        sklearn.feature_extraction.text.TfidfVectorizer
        sklearn.cluster.MiniBatchKMeans

    """
    data = list([p for p in paths])
    dirs = [os.path.dirname(p.replace('\\', '/')) for p in data]
    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
        stop_words=stop_words)
    X = vectorizer.fit_transform(dirs)
    algo = sklearn.cluster.MiniBatchKMeans
    clustering = algo(compute_labels=True, n_clusters=n_clusters)
    clustering.fit(X)
    def __cluster_name(center, vectorizer, n_clusters, threshold):
        df = pd.DataFrame(data={'feature': vectorizer.get_feature_names(),
                                'weight': center})
        df.sort_values(by=['weight', 'feature'], ascending=False, inplace=True)
        if (df['weight'] <= threshold).all():
            return ''
        df = df[df['weight'] > threshold]
        return '.'.join(df['feature'].tolist())
    cluster_names = [__cluster_name(center, vectorizer, n_clusters, 0.4)
                     for center in clustering.cluster_centers_]
    components = [cluster_names[lbl] for lbl in clustering.labels_]
    rv = pd.DataFrame(data={'path': data, 'component': components})
    rv.sort_values(by='component', inplace=True)
    return rv