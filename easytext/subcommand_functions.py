from empath import Empath
import re
import pandas as pd
import spacy
from collections import Counter
from argparse import ArgumentParser

from .algorithms import glove, lda, nmf
from .reports import write_report, make_human_report, make_summary
from .easytext import easyparse

def common_args(subparser):
    subparser.add_argument('infiles', nargs='+', help='Input files.')
    subparser.add_argument('outfile', help='Output file.')

    subparser.add_argument('-dn','--doclabelcol', type=str, required=False, help='Column name for document title/id.')
    subparser.add_argument('-c','--textcol', type=str, default='text', help='Column name of text data (if excel file provided).')

    subparser.add_argument('-nhd','--nohdfonfail', action='store_true', help='Don\'t write hdf if the data is too big for excel.')

    
def subcommand_wordcount_args(main_parser, main_subparsers):
    newp = main_subparsers.add_parser('wordcount', help='Word count across corpus, either by (a) manually selecting words to count or (b) selecting a minimum frequency of words to count.')
    common_args(newp)
    newp.add_argument('-w','--words', type=str, help='Comma-separated words to count in each document. Each word will be a column. i.e. "word1,word2" to count just two words.')
    newp.add_argument('-m','--min_tf', type=int, default=1, help='Count all words that appear a minimum of min_tf times in corpus. Warning: could lead to really large & sparse output files.')
    newp.add_argument('-hr','--human-readable', action='store_true', help='Organize output to be read by humans.')

def subcommand_wordcount(texts, docnames, args):
    #print('converting', len(texts), 'texts to bags-of-words')
    nlp = spacy.load('en')
    if args.words is not None:
        counts = list()
        twords = [w.strip() for w in args.words.split(',')]
        assert(len(twords) > 0)
        for pw in easyparse(nlp,texts,enable=['wordlist',]):
            if len(pw['wordlist']) > 0:
                wc = dict()
                for tword in twords:
                    wc[tword] = pw['wordlist'].count(tword)
                counts.append(wc)
    else:
        assert(args.min_tf > 0)
        print('Counting all words with min_tf of', args.min_tf)

        docbow = list()
        for pw in easyparse(nlp,texts,enable=['wordlist',]):
            if len(pw['wordlist']) > 0:
                docbow.append(pw['wordlist'])
        freq = Counter([w for d in docbow for w in d])
        twords = [w for w,c in freq.items() if c >= args.min_tf]
        print('Kept', len(twords), 'words in vocab to count.')
        counts = list()
        for bow in docbow:
            wc = dict()
            for tword in twords:
                wc[tword] = bow.count(tword)
            counts.append(wc)

    # build output sheets
    sheets = list()
    df = pd.DataFrame(counts,index=docnames)
    if args.human_readable:
        hdf = make_human_report(df)
        sheets.append(('humancounts',hdf))
    else:
        sheets.append(('counts',df))

    # actually write report
    final_fname = write_report(
        args.outfile, 
        sheets, 
        hdf_if_fail=not args.nohdfonfail and not args.human_readable, 
        verbose=True,
    )

    return final_fname


def subcommand_sentiment_args(main_parser, main_subparsers):
    newp = main_subparsers.add_parser('sentiment', help='Compute sentiment analysis on corpus using Stanford empath.')
    common_args(newp)
    newp.add_argument('-o','--posneg-only', action='store_true', help='Include only positive and negative emotion categories.')
    newp.add_argument('-n','--no-normalize', action='store_true', help='Don\'t normalize counts by document length.')
    newp.add_argument('-hr','--human-readable', action='store_true', help='Organize output to be read by humans.')


def subcommand_sentiment(texts, docnames, args):
    nlp = spacy.load('en')
    lexicon = Empath()
    if args.posneg_only:
        cats = ['positive_emotion','negative_emotion']
    else:
        cats = None # all the categories

    analyze = lambda t: lexicon.analyze(t, categories=cats, normalize= not args.no_normalize)
    sentiments = [analyze(t) for t in texts]


    df = pd.DataFrame(sentiments,index=docnames)
    summarydf = make_summary(df)

    sheets = list()
    if args.human_readable:
        hdf = make_human_report(df)
        sheets.append( ('report',hdf) )
    else:
        sheets.append( ('report',df))
    sheets.append(('summary',summarydf))

    final_fname = write_report(
        args.outfile, 
        sheets, 
        hdf_if_fail=not args.nohdfonfail and not args.human_readable, 
        verbose=True,
    )

    return final_fname


def subcommand_entities_args(main_parser, main_subparsers):
    newp = main_subparsers.add_parser('entities', help='Run Spacy Named Entity Recognition (NER).')
    common_args(newp)
    newp.add_argument('-m','--min_tf', type=int, default=1, help='Minimum number of total entity occurrences to include in the model.')
    newp.add_argument('-hr','--human-readable', action='store_true', help='Organize output to be read by humans.')
    newp.add_argument('-ut','--use-types', type=str, help='Entity types to use. Format: "etype1,etype2".')
    newp.add_argument('-it','--ignore-types', type=str, help='Entity types to ignore. Format: "etype1,etype2".')

def subcommand_entities(texts, docnames, args):
    assert(args.min_tf > 0)
    assert(not (args.ignore_types is not None and args.use_types is not None))
    
    nlp = spacy.load('en')

    # decide which entities to use
    if args.use_types is not None:
        pipeargs = {'use_ent_types': [t.strip() for t in args.use_types.split(',')]}
    if args.ignore_types is not None:
        pipeargs = {'ignore_ent_types': [t.strip() for t in args.ignore_types.split(',')]}
    else:
        # by default, remove these:
        ignorelist = 'DATE,TIME,PERCENT,MONEY,QUANTITY,ORDINAL,CARDINAL'
        pipeargs = {'ignore_ent_types': [t.strip() for t in ignorelist.split(',')]}

    # parse all entities
    docents = list()
    for pw in easyparse(nlp,texts,enable=['entlist',],pipeargs=pipeargs):
        if len(pw['entlist']) > 0:
            docents.append([n for n,e in pw['entlist']])

    # determine ents to count
    freq = Counter([e for d in docents for e in d])
    tents = [w for w,c in freq.items() if c >= args.min_tf]
    if len(tents) == 0:
        raise Exception('No ents reached the count threshold given.')
    print('Kept', len(tents), 'entities to count.')

    # count entities per-doc
    counts = list()
    for ents in docents:
        wc = dict()
        for tent in tents:
            wc[tent] = ents.count(tent)
        counts.append(wc)


    # build output sheets
    sheets = list()
    df = pd.DataFrame(counts,index=docnames)
    if args.human_readable:
        hdf = make_human_report(df)
        sheets.append(('humanents',hdf))
    else:
        sheets.append(('ents',df))

    # actually write report
    final_fname = write_report(
        args.outfile, 
        sheets, 
        hdf_if_fail=not args.nohdfonfail and not args.human_readable, 
        verbose=True,
    )
    return final_fname



def subcommand_topicmodel_args(main_parser, main_subparsers):
    newp = main_subparsers.add_parser('topicmodel', help='Run topic modeling algorithms (LDA or NMF).')
    common_args(newp)
    newp.add_argument('-n', '--numtopics', type=int, required=True, help='Numer of topics.')
    newp.add_argument('-t','--type', type=str, default='lda', help="From ('lda','nmf') choose algorithm.")
    newp.add_argument('-s','--seed', type=int, default=0, help='Seed to be used to init topic model.')
    newp.add_argument('-m','--min_tf', type=int, default=0, help='Seed to be used to init topic model.')
    newp.add_argument('-nswm','--nosave_wordmatrix', action='store_true', help='Don\'t save word matrix in excel (helps to make smaller files).')

def subcommand_topicmodel(texts, docnames, args):
    assert(args.numtopics > 0)
    assert(args.type.lower() in ('lda','nmf'))
    assert(args.numtopics < len(texts))
    
    nlp = spacy.load('en')

    print('converting', len(texts), 'texts to bags-of-words')
    bows = list()
    for pw in easyparse(nlp,texts,enable=['wordlist',]):
        if len(pw['wordlist']) > 0:
            bows.append(pw['wordlist'])

    print('performing topic modeling with', args.numtopics, 'topics.')
    tmfunc = nmf if args.type.lower() == 'nmf' else lda
    model = tmfunc(
        docbows=bows, 
        n_topics=args.numtopics, 
        docnames=docnames,
        min_tf=args.min_tf,
        random_state=args.seed,
    )

    print('writing output report')
    final_fname = model.write_report(
        args.outfile, 
        save_wordmatrix=not args.nosave_wordmatrix, 
        featurename='topic',
        hdf_if_fail = not args.nohdfonfail,
    )
    return final_fname



def subcommand_glove_args(main_parser, main_subparsers):
    newp = main_subparsers.add_parser('glove', help='Run glove algorithm.')
    common_args(newp)
    newp.add_argument('-d', '--dimensions', type=int, required=True, help='Numer of embedding dimensions.')
    newp.add_argument('-kw','--keywords', type=str, help='Keywords orient embedding dimensions. Format: "word1,word2|word3", where vector dimension 1 is "word1" + "word2", and dimension 2 is the vector "word3" rejected from dimension 1.')
    newp.add_argument('-m','--min_tf', type=int, default=0, help='Minimum number of word occurrences to include in the model.')
    newp.add_argument('-nswm','--nosave_wordmatrix', action='store_true', help='Don\'t save word matrix in excel (helps to make smaller files).')

def subcommand_glove(texts, docnames, args):
    assert(args.dimensions > 0)
    assert(args.dimensions < len(texts))
    keywords = parse_keywords(args.keywords)
    
    nlp = spacy.load('en')

    # parse texts using spacy
    print('converting', len(texts), 'texts to sentence lists')
    docsents = list()
    for pw in easyparse(nlp,texts,enable=['sentlist']):
        if len(pw['sentlist']) > 0:
            docsents.append(pw['sentlist'])

    print('running glove algorithm with n =', args.dimensions)
    model = glove(
        docsents, 
        args.dimensions,
        docnames=docnames,
        keywords=keywords,
        min_tf=args.min_tf,
    )

    print('writing output report to', args.outfile)
    final_fname = model.write_report(
        args.outfile, 
        save_wordmatrix= not args.nosave_wordmatrix, 
        featurename='dimension',
        hdf_if_fail = not args.nohdfonfail,
    )
    
    return final_fname


'''

parent_parser -> master_parser
main_parser -> grammar_parser
service_subparsers -> grammar_subparsers


parent_parser
    main_parser
        service_subparsers
        service_parser
            action_subparser


parser -> main_parser
subparsers -> main_subparsers

sum_parser -> grammar_parser
sum_subparser -> grammar_subparser

main_parser
main_subparsers
    -> grammar_parser
    -> multi_parser

main_parser = argparse.ArgumentParser()
main_parser.add_argument('-i', '--stdin', action='store_true')

main_subparsers = main_parser.add_subparsers(dest='func')

grammar_parser = main_subparsers.add_parser('grammar')
grammar_parser.add_argument('numbers', type=int, nargs='*')

mult_parser = main_subparsers.add_parser('mult')
mult_parser.add_argument('numbers', type=int, nargs='*')
'''



def subcommand_grammar_args(main_parser, main_subparsers):
    grammar_parser = main_subparsers.add_parser('grammar', help='Run grammatical expression extraction.')
    grammar_subparsers = grammar_parser.add_subparsers(title='grammar', dest='grammar_command')
    grammar_subparsers.required = True
    
    # noun phrases
    np_parser = grammar_subparsers.add_parser('nounphrases', help='Extract noun phrases.',)
    common_args(np_parser)
    np_parser.add_argument('-m','--min_tf', type=int, default=1, help='Min phrase count to include.')
    
    # noun - verb pairs
    nv_parser = grammar_subparsers.add_parser('nounverbs', help='Extract noun-verb pairs.',)
    common_args(nv_parser)
    nv_parser.add_argument('-m','--min_tf', type=int, default=1, help='Min phrase count to include.')
    
    # entity - verb pairs
    ev_parser = grammar_subparsers.add_parser('entverbs', help='Extract entity-verb pairs.',)
    common_args(ev_parser)
    ev_parser.add_argument('-m','--min_tf', type=int, default=1, help='Min phrase count to include.')
    

def subcommand_grammar(texts, docnames, args):

    return 'shit.xlsx'


all_subcommands = {
    'wordcount':{'argparser':subcommand_wordcount_args, 'command':subcommand_wordcount},
    'sentiment':{'argparser':subcommand_sentiment_args, 'command':subcommand_sentiment},
    'entities':{'argparser':subcommand_entities_args, 'command':subcommand_entities},
    'topicmodel':{'argparser':subcommand_topicmodel_args, 'command':subcommand_topicmodel},
    'glove':{'argparser':subcommand_glove_args, 'command':subcommand_glove},
    'grammar':{'argparser':subcommand_grammar_args, 'command':subcommand_grammar},
}














