"""Name-resolution-only regressions; no trading strategy changes."""
import pytest
from scanner.polymarket_executor import (
    _names_match, _name_in_text, _event_matches, _event_search_terms,
    _validated_market_side, LONG_SIDE, SHORT_SIDE, PermanentExecutionError,
)

@pytest.mark.parametrize('a,b', [
    ('J. C. Prado Angelo', 'Juan Carlos Prado'),
    ('Juan Carlos Prado Angelo', 'Juan Carlos Prado'),
    ('Juan Carlos Prado', 'J. C. Prado Angelo'),
    ('B. Shick', 'Braden Shick'),
    ('Dar. Blanch', 'Darwin Blanch'),
    ('G. Heide', 'Gustavo Heide'),
])
def test_safe_aliases(a,b):
    assert _names_match(a,b)

@pytest.mark.parametrize('a,b', [
    ('J. C. Prado Angelo','Juan Carlos Silva'),
    ('J. C. Prado Angelo','Juan Prado'),
    ('J. Prado Angelo','Juan Prado'),
    ('J. C. Prado Angelo','Juan Carlos Prado Silva'),
    ('J. C. Prado Angelo','Juan Carlos Angelo'),
    ('G. Heide','Gustavo Prado'),
])
def test_disallowed_aliases(a,b):
    assert not _names_match(a,b)

def test_compound_name_event_and_moneyline_validation():
    event={'title':'Juan Carlos Prado vs Gustavo Heide', 'markets':[], 'closed':False}
    assert _event_matches(event, 'J. C. Prado Angelo','G. Heide')
    assert _name_in_text('J. C. Prado Angelo',event['title'])
    assert 'prado heide' in _event_search_terms('J. C. Prado Angelo','G. Heide')
    market={'sportsMarketType':'SPORTS_MARKET_TYPE_MONEYLINE','active':True,'closed':False,
        'marketSides':[{'team':{'name':'Gustavo Heide'},'long':False},
                       {'team':{'name':'Juan Carlos Prado'},'long':True}]}
    assert _validated_market_side(market,'J. C. Prado Angelo','G. Heide') == LONG_SIDE
    assert _validated_market_side(market,'G. Heide','J. C. Prado Angelo') == SHORT_SIDE

def test_multiple_matching_sides_fail_closed():
    market={'sportsMarketType':'SPORTS_MARKET_TYPE_MONEYLINE','active':True,'closed':False,
        'marketSides':[{'team':{'name':'Juan Carlos Prado'},'long':True},
                       {'team':{'name':'Juan Carlos Prado Angelo'},'long':False}]}
    with pytest.raises(PermanentExecutionError,match='do not map uniquely'):
        _validated_market_side(market,'J. C. Prado Angelo','G. Heide')

def test_reject_non_moneyline_unchanged():
    market={'sportsMarketType':'SPORTS_MARKET_TYPE_FUTURE','active':True,
            'marketSides':[{'team':{'name':'Juan Carlos Prado'},'long':True},
                           {'team':{'name':'Gustavo Heide'},'long':False}]}
    with pytest.raises(PermanentExecutionError,match='not_moneyline'):
        _validated_market_side(market,'J. C. Prado Angelo','G. Heide')


def test_initial_only_identity_requires_unique_side():
    # J. C. can represent either Juan Carlos or Jose Carlos. We do not
    # invent a distinction, and must reject when both market sides map.
    market={'sportsMarketType':'SPORTS_MARKET_TYPE_MONEYLINE','active':True,
            'marketSides':[{'team':{'name':'Juan Carlos Prado'},'long':True},
                           {'team':{'name':'Jose Carlos Prado'},'long':False}]}
    with pytest.raises(PermanentExecutionError,match='do not map uniquely'):
        _validated_market_side(market,'J. C. Prado Angelo','G. Heide')
