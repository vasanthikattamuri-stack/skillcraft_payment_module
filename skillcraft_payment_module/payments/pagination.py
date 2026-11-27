"""Pagination for the payment history endpoint (independent of project settings)."""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from . import conf


class PaymentHistoryPagination(PageNumberPagination):
    page_size_query_param = "page_size"  # ?page_size=20
    max_page_size = 50

    def get_page_size(self, request):
        self.page_size = conf.history_page_size()
        return super().get_page_size(request)

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "message": "Payment history fetched successfully",
                "data": {
                    "count": self.page.paginator.count,
                    "total_pages": self.page.paginator.num_pages,
                    "current_page": self.page.number,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                    "results": data,
                },
            }
        )
