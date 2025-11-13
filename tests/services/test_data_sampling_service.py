# tests/services/test_data_sampling_service.py
"""
Unit tests for DataSamplingService
"""

from datetime import date, datetime

import pytest

from flask_app.services.data_sampling_service import DataSamplingService


class TestDataSamplingService:
    """Test DataSamplingService"""

    def test_calculate_sample_size_small_dataset(self):
        """Test sample size calculation for small datasets"""
        assert DataSamplingService._calculate_sample_size(10) == 10
        assert DataSamplingService._calculate_sample_size(50) == 10
        assert DataSamplingService._calculate_sample_size(99) == 10

    def test_calculate_sample_size_medium_dataset(self):
        """Test sample size calculation for medium datasets"""
        size_100 = DataSamplingService._calculate_sample_size(100)
        assert 10 <= size_100 <= 50

        size_500 = DataSamplingService._calculate_sample_size(500)
        assert 10 <= size_500 <= 50

    def test_calculate_sample_size_large_dataset(self):
        """Test sample size calculation for large datasets"""
        size = DataSamplingService._calculate_sample_size(10000)
        assert size == DataSamplingService.MAX_SAMPLE_SIZE

    def test_calculate_sample_size_with_requested_size(self):
        """Test sample size calculation with requested size"""
        assert DataSamplingService._calculate_sample_size(1000, requested_size=25) == 25
        assert DataSamplingService._calculate_sample_size(100, requested_size=5) == 10  # Min enforced
        assert DataSamplingService._calculate_sample_size(100, requested_size=100) == 50  # Max enforced

    def test_get_completeness_level(self):
        """Test completeness level calculation"""
        assert DataSamplingService._get_completeness_level(85.0) == "high"
        assert DataSamplingService._get_completeness_level(80.0) == "high"
        assert DataSamplingService._get_completeness_level(65.0) == "medium"
        assert DataSamplingService._get_completeness_level(50.0) == "medium"
        assert DataSamplingService._get_completeness_level(30.0) == "low"
        assert DataSamplingService._get_completeness_level(0.0) == "low"

    def test_cache_functionality(self):
        """Test cache get/set/clear functionality"""
        # Clear cache first
        DataSamplingService._clear_cache()

        # Set cache
        key = "test_key"
        value = {"test": "data"}
        DataSamplingService._set_cache(key, value)

        # Get cached value
        cached = DataSamplingService._get_cached(key)
        assert cached == value

        # Clear cache
        DataSamplingService._clear_cache()
        cached_after_clear = DataSamplingService._get_cached(key)
        assert cached_after_clear is None

    def test_cache_key_generation(self):
        """Test cache key generation"""
        key1 = DataSamplingService._get_cache_key("contact", 20, None)
        key2 = DataSamplingService._get_cache_key("contact", 20, None)
        assert key1 == key2

        key3 = DataSamplingService._get_cache_key("contact", 20, 1)
        assert key1 != key3

        key4 = DataSamplingService._get_cache_key("volunteer", 20, None)
        assert key1 != key4
