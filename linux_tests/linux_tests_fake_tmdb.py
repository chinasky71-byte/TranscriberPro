# -*- coding: utf-8 -*-
"""Client TMDB finto per i test (nessuna rete)."""


class FakeTmdb:
    api_key = 'k'

    def __init__(self, parsed=None, resolved=None, media=None, poster=None, boom=False):
        self.parsed = parsed or {}
        self.resolved = resolved
        self.media = media
        self.poster = poster
        self.boom = boom
        self.parse_calls = []
        self.media_calls = []
        self.download_calls = []

    def parse_filename(self, name, allow_absolute=True):
        self.parse_calls.append(name)
        if self.boom:
            raise RuntimeError('boom')
        return self.parsed

    def resolved_episode(self, title, absolute, year=None):
        return self.resolved

    def _pre_clean_title(self, t):
        return t.replace('.', ' ')

    def _clean_title(self, t):
        return t.strip().title()

    def get_media_info(self, filename):
        self.media_calls.append(filename)
        if self.boom:
            raise RuntimeError('boom')
        return self.media

    def download_poster(self, poster_path, title):
        self.download_calls.append((poster_path, title))
        return self.poster
