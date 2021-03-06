from django.utils.encoding import python_2_unicode_compatible
from esi.clients import esi_client_factory
from django.conf import settings
from bravado.exception import HTTPNotFound, HTTPUnprocessableEntity
import evelink

@python_2_unicode_compatible
class ObjectNotFound(Exception):
    def __init__(self, id, type):
        self.id = id
        self.type = type

    def __str__(self):
        return '%s with ID %s not found.' % (self.type, self.id)


@python_2_unicode_compatible
class Entity(object):
    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<{} ({}): {}>".format(self.__class__.__name__, self.id, self.name)

    def __bool__(self):
        return bool(self.id)

    def __eq__(self, other):
        return self.id == other.id


class Corporation(Entity):
    def __init__(self, provider, id, name, ticker, ceo_id, members, alliance_id):
        super(Corporation, self).__init__(id, name)
        self.provider = provider
        self.ticker = ticker
        self.ceo_id = ceo_id
        self.members = members
        self.alliance_id = alliance_id

    @property
    def alliance(self):
        if self.alliance_id:
            return self.provider.get_alliance(self.alliance_id)
        return Entity(None, None)

    @property
    def ceo(self):
        return self.provider.get_character(self.ceo_id)


class Alliance(Entity):
    def __init__(self, provider, id, name, ticker, corp_ids, executor_corp_id):
        super(Alliance, self).__init__(id, name)
        self.provider = provider
        self.ticker = ticker
        self.corp_ids = corp_ids
        self.executor_corp_id = executor_corp_id

    def corp(self, id):
        assert id in self.corp_ids
        return self.provider.get_corp(id)

    @property
    def corps(self):
        return sorted([self.corp(id) for id in self.corp_ids], key=lambda x: x.name)

    @property
    def executor_corp(self):
        return self.provider.get_corp(self.executor_corp_id)


class Character(Entity):
    def __init__(self, provider, id, name, corp_id, alliance_id):
        super(Character, self).__init__(id, name)
        self.provider = provider
        self.corp_id = corp_id
        self.alliance_id = alliance_id

    @property
    def corp(self):
        return self.provider.get_corp(self.corp_id)

    @property
    def alliance(self):
        if self.alliance_id:
            return self.provider.get_alliance(self.alliance_id)
        return Entity(None, None)


class EveProvider:
    def get_alliance(self, alliance_id):
        """
        :return: an Alliance object for the given ID
        """
        raise NotImplementedError()

    def get_corp(self, corp_id):
        """
        :return: a Corporation object for the given ID
        """
        raise NotImplementedError()

    def get_character(self, corp_id):
        """
        :return: a Character object for the given ID
        """
        raise NotImplementedError()


@python_2_unicode_compatible
class EveSwaggerProvider(EveProvider):
    def __init__(self, token=None, adapter=None):
        self.client = esi_client_factory(token=token)
        self.adapter = adapter or self

    def __str__(self):
        return 'esi'

    def get_alliance(self, id):
        try:
            data = self.client.Alliance.get_alliances_alliance_id(alliance_id=id).result()
            corps = self.client.Alliance.get_alliances_alliance_id_corporations(alliance_id=id).result()
            model = Alliance(
                self.adapter,
                id,
                data['alliance_name'],
                data['ticker'],
                corps,
                data['executor_corp'],
            )
            return model
        except HTTPNotFound:
            raise ObjectNotFound(id, 'alliance')

    def get_corp(self, id):
        try:
            data = self.client.Corporation.get_corporations_corporation_id(corporation_id=id).result()
            model = Corporation(
                self.adapter,
                id,
                data['corporation_name'],
                data['ticker'],
                data['ceo_id'],
                data['member_count'],
                data['alliance_id'] if 'alliance_id' in data else None,
            )
            return model
        except HTTPNotFound:
            raise ObjectNotFound(id, 'corporation')

    def get_character(self, id):
        try:
            data = self.client.Character.get_characters_character_id(character_id=id).result()
            alliance_id = self.adapter.get_corp(data['corporation_id']).alliance_id
            model = Character(
                self.adapter,
                id,
                data['name'],
                data['corporation_id'],
                alliance_id,
            )
            return model
        except (HTTPNotFound, HTTPUnprocessableEntity):
            raise ObjectNotFound(id, 'character')


@python_2_unicode_compatible
class EveXmlProvider(EveProvider):
    def __init__(self, api_key=None, adapter=None):
        """
        :param api_key: eveonline.EveApiKeyPair
        """
        self.api = evelink.api.API(api_key=(api_key.api_id, api_key.api_key)) if api_key else evelink.api.API()
        self.adapter = adapter or self

    def __str__(self):
        return 'xml'

    def get_alliance(self, id):
        api = evelink.eve.EVE(api=self.api)
        alliances = api.alliances().result
        try:
            results = alliances[int(id)]
        except KeyError:
            raise ObjectNotFound(id, 'alliance')
        model = Alliance(
            self.adapter,
            id,
            results['name'],
            results['ticker'],
            results['member_corps'],
            results['executor_id'],
        )
        return model

    def get_corp(self, id):
        api = evelink.corp.Corp(api=self.api)
        try:
            corpinfo = api.corporation_sheet(corp_id=int(id)).result
        except evelink.api.APIError as e:
            if int(e.code) == 523:
                raise ObjectNotFound(id, 'corporation')
            raise e
        model = Corporation(
            self.adapter,
            id,
            corpinfo['name'],
            corpinfo['ceo']['id'],
            corpinfo['members']['current'],
            corpinfo['ticker'],
            corpinfo['alliance']['id'] if corpinfo['alliance'] else None,
        )
        return model

    def _build_character(self, result):
        return Character(
            self.adapter,
            result['id'],
            result['name'],
            result['corp']['id'],
            result['alliance']['id'],
        )

    def get_character(self, id):
        api = evelink.eve.EVE(api=self.api)
        try:
            charinfo = api.character_info_from_id(id).result
        except evelink.api.APIError as e:
            if int(e.code) == 105:
                raise ObjectNotFound(id, 'character')
            raise e
        return self._build_character(charinfo)


class EveAdapter(EveProvider):
    """
    Redirects queries to appropriate data source.
    """
    def __init__(self, char_provider, corp_provider, alliance_provider):
        self.char_provider = char_provider
        self.corp_provider = corp_provider
        self.alliance_provider = alliance_provider
        self.char_provider.adapter = self
        self.corp_provider.adapter = self
        self.alliance_provider.adapter = self

    def __repr__(self):
        return "<{} (char:{}, corp:{}, alliance:{})>".format(self.__class__.__name__, str(self.char_provider), str(self.corp_provider), str(self.alliance_provider))

    def get_character(self, id):
        return self.char_provider.get_character(id)

    def get_corp(self, id):
        return self.corp_provider.get_corp(id)

    def get_alliance(self, id):
        return self.alliance_provider.get_alliance(id)


def eve_adapter_factory(character_source=settings.EVEONLINE_CHARACTER_PROVIDER, corp_source=settings.EVEONLINE_CORP_PROVIDER, alliance_source=settings.EVEONLINE_ALLIANCE_PROVIDER, api_key=None, token=None):
    sources = [character_source, corp_source, alliance_source]
    providers = []

    xml = EveXmlProvider(api_key=api_key)
    esi = EveSwaggerProvider(token=token)

    for source in sources:
        if source == 'xml':
            providers.append(xml)
        elif source == 'esi':
            providers.append(esi)
        else:
            raise ValueError('Unrecognized data source "%s"' % source)
    return EveAdapter(providers[0], providers[1], providers[2])
