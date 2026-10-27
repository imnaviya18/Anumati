from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.policy.models import SyncException
from apps.policy.services import _assert_policy_governor
from apps.policy.sync import ingest_mock_event, reconcile


class EventInput(serializers.Serializer):
    event_id = serializers.CharField(max_length=128)
    source_id = serializers.CharField(max_length=128)
    reason = serializers.CharField(max_length=2000)
    payload = serializers.JSONField()


class ResolutionInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=["KEEP_LOCAL", "ACCEPT_SOURCE", "REASSIGN"])
    reason = serializers.CharField(max_length=2000)
    owner_id = serializers.IntegerField(required=False)


def serialize(item):
    return {"id":str(item.id), "event_id":item.event_id, "source_id":item.source_record.source_id,
        "source_system":item.source_system, "state":item.state, "version":item.version,
        "owner_id":item.owner_id,"owner":item.owner.username,"reason":item.reason,
        "local_snapshot":item.local_snapshot,"incoming_snapshot":item.incoming_snapshot,
        "current_source_snapshot":item.source_record.payload,"baseline_version":item.baseline_version,
        "current_source_version":item.source_record.version,"resolution":item.resolution,
        "resolution_reason":item.resolution_reason,"resolved_at":item.resolved_at,"created_at":item.created_at}


class SyncExceptionsView(APIView):
    def get(self, request):
        _assert_policy_governor(request.user)
        qs = SyncException.objects.select_related("owner", "source_record")
        if request.query_params.get("state") in {"OPEN","RESOLVED"}:
            qs = qs.filter(state=request.query_params["state"])
        paginator = PageNumberPagination()
        paginator.page_size = 20
        return paginator.get_paginated_response([serialize(i) for i in paginator.paginate_queryset(qs, request)])

    def post(self, request):
        data = EventInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(serialize(ingest_mock_event(actor=request.user, **data.validated_data)),status=201)


class SyncExceptionActionView(APIView):
    def post(self, request, exception_id):
        _assert_policy_governor(request.user)
        get_object_or_404(SyncException, pk=exception_id)
        data = ResolutionInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        if "owner_id" in values:
            values["owner"] = get_object_or_404(get_user_model(), pk=values.pop("owner_id"))
        item = reconcile(actor=request.user, exception_id=exception_id, **values)
        return Response(serialize(item))
