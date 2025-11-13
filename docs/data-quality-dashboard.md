# Data Quality Dashboard

## Overview

The Data Quality Dashboard provides administrators with a comprehensive view of data completeness across all entities in the database. Unlike the DQ Inbox (which focuses on import violations), the Data Quality Dashboard offers field-level completeness metrics for all entities, helping administrators identify data quality issues and track improvement over time.

## Features

### Overall Health Score

- **Weighted Health Score**: Calculates an overall data quality health score (0-100%) based on field completeness across all entities
- **Visual Indicators**: Color-coded health score (good/warning/critical) with visual feedback
- **Real-time Updates**: Health score updates automatically when data changes

### Entity-Level Metrics

The dashboard tracks completeness metrics for the following entity types:

- **Contacts**: Core contact information (name, email, phone, address, demographics)
- **Volunteers**: Volunteer-specific fields (title, industry, skills, interests, availability, hours)
- **Students**: Student-specific fields (grade, enrollment date, student ID, graduation date)
- **Teachers**: Teacher-specific fields (certification, subject areas, hire date, employee ID)
- **Events**: Event information (title, description, dates, location, capacity, cost)
- **Organizations**: Organization details (name, description, contact info, addresses)
- **Users**: User account information (username, email, name)

### Field-Level Completeness

For each entity type, the dashboard displays:

- **Field Name**: The name of the field being measured
- **Total Records**: Total number of records for the entity
- **Records With Value**: Number of records with a value for the field
- **Records Without Value**: Number of records missing the field
- **Completeness Percentage**: Percentage of records with the field populated
- **Status Indicator**: Visual status (good ≥80%, warning 50-79%, critical <50%)

### Organization Filtering

- **Super Admins**: Can filter metrics by organization or view all organizations
- **Organization Admins**: Automatically filtered to their organization
- **Organization Context**: Metrics respect organization boundaries via `ContactOrganization` relationships

### Export Functionality

- **CSV Export**: Export all metrics as CSV for analysis in Excel/Google Sheets
- **JSON Export**: Export metrics as JSON for programmatic analysis
- **Timestamped Exports**: All exports include timestamps for tracking changes over time

## Access

### Navigation

- **Admin Dashboard**: Link in "Quick Actions" section
- **Admin Menu**: "Admin" → "Data Quality" dropdown item
- **Direct URL**: `/admin/data-quality`

### Permissions

- **Required Permission**: `view_users` (same as other admin features)
- **Organization Context**: Respects organization membership for non-super admins
- **Audit Logging**: All dashboard access and exports are logged in `AdminLog`

## API Endpoints

### Get Overall Metrics

```
GET /admin/data-quality/api/metrics?organization_id=<org_id>
```

Returns overall health score and entity-level metrics.

**Response**:
```json
{
  "overall_health_score": 75.5,
  "total_entities": 1500,
  "timestamp": "2024-01-15T10:30:00Z",
  "entity_metrics": [
    {
      "entity_type": "contact",
      "total_records": 500,
      "overall_completeness": 80.2,
      "key_metrics": {
        "email": {"percentage": 85.0, "count": 425},
        "phone": {"percentage": 70.0, "count": 350},
        "address": {"percentage": 60.0, "count": 300}
      }
    }
  ]
}
```

### Get Entity Metrics

```
GET /admin/data-quality/api/entity/<entity_type>?organization_id=<org_id>
```

Returns field-level completeness metrics for a specific entity type.

**Entity Types**: `contact`, `volunteer`, `student`, `teacher`, `event`, `organization`, `user`

**Response**:
```json
{
  "entity_type": "contact",
  "total_records": 500,
  "overall_completeness": 80.2,
  "key_metrics": {
    "email": {"percentage": 85.0, "count": 425},
    "phone": {"percentage": 70.0, "count": 350},
    "address": {"percentage": 60.0, "count": 300}
  },
  "fields": [
    {
      "field_name": "email",
      "total_records": 500,
      "records_with_value": 425,
      "records_without_value": 75,
      "completeness_percentage": 85.0,
      "status": "good"
    }
  ]
}
```

### Export Metrics

```
GET /admin/data-quality/api/export?format=<csv|json>&organization_id=<org_id>
```

Exports metrics as CSV or JSON.

**Parameters**:
- `format`: `csv` or `json` (required)
- `organization_id`: Optional organization filter (super admins only)

**Response**: File download with appropriate content type and filename

## Caching

- **Cache TTL**: 5 minutes (configurable via `DataQualityService._cache_ttl_seconds`)
- **Cache Key**: Includes entity type and organization ID
- **Cache Invalidation**: Automatic after TTL expires
- **Manual Refresh**: "Refresh" button clears cache and reloads metrics

## Performance Considerations

### Query Optimization

- **Efficient Queries**: Uses SQL aggregations (`COUNT`, `DISTINCT`) for performance
- **Indexed Fields**: Leverages existing database indexes on key fields
- **Relationship Queries**: Optimized joins for email/phone/address relationships
- **Organization Filtering**: Uses subqueries for efficient organization filtering

### Scalability

- **Caching**: Reduces database load for frequently accessed metrics
- **Lazy Loading**: Entity details loaded on-demand when selected
- **Pagination**: Future enhancement for large datasets
- **Background Jobs**: Future enhancement for pre-computed metrics

## Usage Examples

### Monitoring Data Quality

1. **View Overall Health**: Check the overall health score on the dashboard
2. **Identify Problem Areas**: Look for entities with low completeness scores
3. **Drill Down**: Click on an entity card to see field-level metrics
4. **Export for Analysis**: Export metrics to CSV/JSON for deeper analysis
5. **Track Progress**: Compare exports over time to track improvement

### Improving Data Quality

1. **Prioritize Critical Fields**: Focus on fields with "critical" status (<50% completeness)
2. **Target Low-Hanging Fruit**: Address fields with "warning" status (50-79% completeness)
3. **Set Goals**: Use the dashboard to set and track completeness goals
4. **Monitor Trends**: Export metrics regularly to track trends over time

### Organization-Specific Analysis

1. **Filter by Organization**: Super admins can filter metrics by organization
2. **Compare Organizations**: Export metrics for multiple organizations and compare
3. **Identify Best Practices**: Find organizations with high data quality and learn from them

## Status Indicators

### Health Score Status

- **Good** (≥80%): Green indicator, indicates healthy data quality
- **Warning** (50-79%): Yellow indicator, indicates areas for improvement
- **Critical** (<50%): Red indicator, indicates significant data quality issues

### Field Status

- **Good** (≥80%): Green badge, field is well-populated
- **Warning** (50-79%): Yellow badge, field needs attention
- **Critical** (<50%): Red badge, field has significant gaps

## Technical Details

### Service Layer

The dashboard is powered by `DataQualityService` in `flask_app/services/data_quality_service.py`:

- **Methods**:
  - `get_overall_health_score(organization_id=None)`: Calculate overall health score
  - `get_entity_metrics(entity_type, organization_id=None)`: Get entity-specific metrics
  - `_get_contact_metrics(organization_id=None)`: Calculate contact metrics
  - `_get_volunteer_metrics(organization_id=None)`: Calculate volunteer metrics
  - Similar methods for other entity types

### Relationship Handling

- **ContactOrganization**: Contacts and volunteers linked via `ContactOrganization` are included in organization filtering
- **EventOrganization**: Events linked via `EventOrganization` are included in organization filtering
- **UserOrganization**: Users linked via `UserOrganization` are included in organization filtering

### Field Types

- **Direct Fields**: Fields stored directly on the entity (e.g., `first_name`, `last_name`)
- **Relationship Fields**: Fields stored in related tables (e.g., `email` in `ContactEmail`, `phone` in `ContactPhone`)
- **Required Fields**: Fields that are required (e.g., `first_name`, `last_name`) are checked for non-empty values
- **Optional Fields**: Fields that are optional are checked for non-null values

## Future Enhancements

### Planned Features

- **Trend Analysis**: Track completeness trends over time
- **Goal Setting**: Set and track completeness goals per entity/field
- **Alerts**: Alert administrators when completeness drops below thresholds
- **Bulk Actions**: Bulk update capabilities for improving data quality
- **Data Quality Rules**: Integration with DQ rules from the importer
- **Historical Comparison**: Compare current metrics with historical snapshots

### Potential Improvements

- **Performance**: Background jobs for pre-computed metrics
- **Visualization**: Charts and graphs for trend analysis
- **Export Formats**: Additional export formats (Excel, PDF)
- **Scheduling**: Scheduled exports and reports
- **Integration**: Integration with external data quality tools

## Troubleshooting

### Common Issues

#### Metrics Not Updating

- **Cache**: Metrics are cached for 5 minutes. Click "Refresh" to clear cache
- **Database**: Ensure database queries are completing successfully
- **Permissions**: Verify user has `view_users` permission

#### Organization Filter Not Working

- **Super Admin**: Only super admins can filter by organization
- **Organization Context**: Non-super admins are automatically filtered to their organization
- **Organization Membership**: Verify user is a member of the selected organization

#### Export Failing

- **Format**: Ensure format is `csv` or `json`
- **Permissions**: Verify user has `view_users` permission
- **Size**: Large exports may take time; check browser console for errors

### Performance Issues

- **Cache**: Metrics are cached for 5 minutes to reduce database load
- **Queries**: Large datasets may require query optimization
- **Indexes**: Ensure database indexes are present on key fields
- **Background Jobs**: Consider implementing background jobs for large datasets

## Related Documentation

- **Data Integration Platform Overview**: `docs/data-integration-platform-overview.md`
- **DQ Inbox**: See importer documentation for DQ inbox (import violations)
- **Admin Dashboard**: `docs/commands.md` for admin CLI commands
- **API Documentation**: See API endpoints above for programmatic access

## Support

For issues or questions:

1. **Check Logs**: Review application logs for errors
2. **Verify Permissions**: Ensure user has required permissions
3. **Clear Cache**: Click "Refresh" to clear cache and reload metrics
4. **Check Database**: Verify database queries are completing successfully
5. **Contact Support**: Reach out to the development team for assistance

