"""
The sketch a point belongs to has to be reopened to draw the bore in, and Fusion
refuses when the sketch sits on a model face that a later feature has consumed.

That refusal used to reach the user as a traceback ending in

    RuntimeError: 3 : referencePlane is a BRefFace -
    need to roll timeline back before sketch

which names neither the sketch nor anything to do about it, and abandoned the whole
run -- including the points that would have worked.
"""

from unittest.mock import MagicMock

import pytest

from tm_execute import sketch_plane_of


def sketch(name='Sketch3', plane=None, error=None):
    """A sketch whose referencePlane either answers or raises."""
    s = MagicMock()
    s.name = name
    if error is None:
        type(s).referencePlane = property(lambda self: plane)
    else:
        def boom(self):
            raise error
        type(s).referencePlane = property(boom)
    return s


def test_returns_the_plane_when_fusion_gives_one():
    plane = MagicMock(name='XY plane')
    assert sketch_plane_of(sketch(plane=plane)) is plane


def test_consumed_face_is_explained_and_names_the_sketch():
    err = RuntimeError('3 : referencePlane is a BRefFace - need to roll timeline back before sketch')
    with pytest.raises(RuntimeError) as caught:
        sketch_plane_of(sketch(name='Face sketch', error=err))

    said = str(caught.value)
    # The three things somebody needs: which sketch, why, and what to do about it.
    assert 'Face sketch' in said
    assert 'later feature' in said
    assert 'Roll the timeline back' in said
    assert 'construction plane' in said
    # And the original is kept, so a log still has the API's own words.
    assert caught.value.__cause__ is err


def test_the_message_does_not_leak_the_api_wording():
    err = RuntimeError('3 : referencePlane is a BRefFace - need to roll timeline back before sketch')
    with pytest.raises(RuntimeError) as caught:
        sketch_plane_of(sketch(error=err))
    assert 'BRefFace' not in str(caught.value), 'that phrase means nothing to anyone'


def test_any_other_failure_is_left_alone():
    """Not every RuntimeError from Fusion is this one, and swallowing the rest into a
    message about the timeline would send someone looking in the wrong place."""
    err = RuntimeError('5 : the document is read-only')
    with pytest.raises(RuntimeError) as caught:
        sketch_plane_of(sketch(error=err))
    assert caught.value is err, 'raised as it came, not rewritten'
