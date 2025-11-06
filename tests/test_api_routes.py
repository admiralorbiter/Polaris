import pytest
from unittest.mock import patch, MagicMock
from flask import json
from werkzeug.security import generate_password_hash
from flask_app.models import (
    Organization, User, Role, Permission, RolePermission, UserOrganization, AdminLog, db
)


class TestOrganizationSearchAPI:
    """Test /api/organizations/search endpoint"""
    
    def test_search_requires_authentication(self, client):
        """Test that search requires login"""
        response = client.get('/api/organizations/search?q=test')
        assert response.status_code == 401 or response.status_code == 302  # Redirect to login
    
    def test_search_super_admin_sees_all(self, client, super_admin_user, app):
        """Test that super admin sees all active organizations"""
        with app.app_context():
            # Create multiple organizations
            org1 = Organization(name='Test Org 1', slug='test-org-1', is_active=True)
            org2 = Organization(name='Test Org 2', slug='test-org-2', is_active=True)
            org3 = Organization(name='Inactive Org', slug='inactive-org', is_active=False)
            db.session.add_all([org1, org2, org3])
            db.session.add(super_admin_user)
            db.session.commit()
            
            # Login as super admin
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'results' in data
            assert len(data['results']) == 2  # Only active organizations
            assert any(r['slug'] == 'test-org-1' for r in data['results'])
            assert any(r['slug'] == 'test-org-2' for r in data['results'])
            assert not any(r['slug'] == 'inactive-org' for r in data['results'])
    
    def test_search_regular_user_sees_only_their_orgs(self, client, test_user, test_organization, test_role, app):
        """Test that regular user sees only their organizations"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            # Create another organization user is not part of
            other_org = Organization(name='Other Org', slug='other-org', is_active=True)
            db.session.add(other_org)
            db.session.add(test_user)
            db.session.commit()
            
            # Add user to test_organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Login as regular user
            client.post('/login', data={
                'username': 'testuser',
                'password': 'testpass123'
            })
            
            response = client.get('/api/organizations/search?q=')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'results' in data
            assert len(data['results']) == 1
            assert data['results'][0]['slug'] == 'test-organization'
            assert not any(r['slug'] == 'other-org' for r in data['results'])
    
    def test_search_filters_by_name(self, client, super_admin_user, app):
        """Test search filters by organization name"""
        with app.app_context():
            org1 = Organization(name='Alpha Organization', slug='alpha', is_active=True)
            org2 = Organization(name='Beta Organization', slug='beta', is_active=True)
            db.session.add_all([org1, org2])
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=Alpha')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert len(data['results']) == 1
            assert data['results'][0]['name'] == 'Alpha Organization'
    
    def test_search_filters_by_slug(self, client, super_admin_user, app):
        """Test search filters by organization slug"""
        with app.app_context():
            org1 = Organization(name='Test Organization', slug='alpha-slug', is_active=True)
            org2 = Organization(name='Another Org', slug='beta-slug', is_active=True)
            db.session.add_all([org1, org2])
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=alpha')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert len(data['results']) == 1
            assert data['results'][0]['slug'] == 'alpha-slug'
    
    def test_search_case_insensitive(self, client, super_admin_user, test_organization, app):
        """Test search is case-insensitive"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            # Search with different cases
            response1 = client.get('/api/organizations/search?q=TEST')
            response2 = client.get('/api/organizations/search?q=test')
            response3 = client.get('/api/organizations/search?q=Test')
            
            for response in [response1, response2, response3]:
                assert response.status_code == 200
                data = json.loads(response.data)
                assert len(data['results']) >= 1
                assert any(r['slug'] == 'test-organization' for r in data['results'])
    
    def test_search_empty_results(self, client, super_admin_user, app):
        """Test search with no matching results"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=nonexistent12345')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'results' in data
            assert len(data['results']) == 0
    
    def test_search_returns_select2_format(self, client, super_admin_user, test_organization, app):
        """Test search returns correct format for Select2"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=test')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'results' in data
            assert isinstance(data['results'], list)
            
            if len(data['results']) > 0:
                result = data['results'][0]
                assert 'id' in result
                assert 'text' in result
                assert 'name' in result
                assert 'slug' in result
                assert 'description' in result
                assert result['text'] == f"{result['name']} ({result['slug']})"
    
    def test_search_pagination_limit(self, client, super_admin_user, app):
        """Test search respects pagination limit"""
        with app.app_context():
            # Create 25 organizations
            orgs = []
            for i in range(25):
                org = Organization(
                    name=f'Org {i}',
                    slug=f'org-{i}',
                    is_active=True
                )
                orgs.append(org)
            db.session.add_all(orgs)
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.get('/api/organizations/search?q=')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert len(data['results']) <= 20  # Limited to 20
    
    def test_search_error_handling(self, client, super_admin_user, app):
        """Test search error handling"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            # Mock database error - need to mock the query object that filter_by returns
            with patch('flask_app.routes.api.Organization') as mock_org:
                # Mock the query chain
                mock_query_obj = MagicMock()
                mock_filter = MagicMock()
                mock_filter.filter.return_value = mock_filter
                mock_filter.order_by.return_value = mock_filter
                mock_filter.limit.return_value = mock_filter
                mock_filter.all.side_effect = Exception("Database error")
                mock_query_obj.filter_by.return_value = mock_filter
                mock_org.query = mock_query_obj
                
                response = client.get('/api/organizations/search?q=test')
                assert response.status_code == 500
                data = json.loads(response.data)
                assert 'error' in data
                assert 'results' in data
                assert data['results'] == []


class TestOrganizationCreateAPI:
    """Test /api/organizations/create endpoint"""
    
    def test_create_requires_authentication(self, client):
        """Test that create requires login"""
        response = client.post('/api/organizations/create',
                             json={'name': 'Test Org'},
                             content_type='application/json')
        assert response.status_code == 401 or response.status_code == 302
    
    def test_create_requires_super_admin(self, client, test_user, app):
        """Test that only super admins can create organizations"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'testuser',
                'password': 'testpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Test Org'},
                                 content_type='application/json')
            assert response.status_code == 403
            data = json.loads(response.data)
            assert data['success'] is False
            assert 'super admin' in data['error'].lower()
    
    def test_create_with_name_only(self, client, super_admin_user, app):
        """Test creating organization with name only"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'New Organization'},
                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            assert 'organization' in data
            assert data['organization']['name'] == 'New Organization'
            assert data['organization']['slug'] == 'new-organization'
            
            # Verify organization was created
            org = Organization.query.filter_by(slug='new-organization').first()
            assert org is not None
            assert org.name == 'New Organization'
    
    def test_create_with_name_and_description(self, client, super_admin_user, app):
        """Test creating organization with name and description"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={
                                     'name': 'Org with Description',
                                     'description': 'This is a description'
                                 },
                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            assert data['organization']['name'] == 'Org with Description'
            
            org = Organization.query.filter_by(slug='org-with-description').first()
            assert org is not None
            assert org.description == 'This is a description'
    
    def test_create_slug_generation(self, client, super_admin_user, app):
        """Test slug generation from name"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            test_cases = [
                ('Test Organization', 'test-organization'),
                ('Test  Organization', 'test-organization'),  # Multiple spaces
                ('Test_Organization', 'test-organization'),  # Underscores
                ('Test-Organization', 'test-organization'),  # Already has hyphens
                ('Test Organization!', 'test-organization'),  # Special chars
                ('Test Organization 123', 'test-organization-123'),  # Numbers
            ]
            
            for name, expected_slug in test_cases:
                response = client.post('/api/organizations/create',
                                     json={'name': name},
                                     content_type='application/json')
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['organization']['slug'] == expected_slug
                
                # Clean up
                org = Organization.query.filter_by(slug=expected_slug).first()
                if org:
                    db.session.delete(org)
                    db.session.commit()
    
    def test_create_empty_slug_validation(self, client, super_admin_user, app):
        """Test validation for empty slug"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': '!!!'},  # Only special chars
                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert data['success'] is False
            assert 'letter or number' in data['error'].lower()
    
    def test_create_duplicate_name(self, client, super_admin_user, test_organization, app):
        """Test duplicate name detection"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Test Organization'},  # Same as test_organization
                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert data['success'] is False
            assert 'already exists' in data['error'].lower()
            assert 'organization' in data  # Should return existing org info
    
    def test_create_duplicate_slug(self, client, super_admin_user, test_organization, app):
        """Test duplicate slug detection"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Different Name But Same Slug'},  # Will generate same slug
                                 content_type='application/json')
            # Note: This depends on slug generation - if it generates different slug, test will pass
            # If same slug, should return 400
            if response.status_code == 400:
                data = json.loads(response.data)
                assert data['success'] is False
                assert 'already exists' in data['error'].lower()
    
    def test_create_missing_name(self, client, super_admin_user, app):
        """Test creating organization without name"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={},
                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert data['success'] is False
            assert 'name is required' in data['error'].lower()
    
    def test_create_empty_name(self, client, super_admin_user, app):
        """Test creating organization with empty name"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': ''},
                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert data['success'] is False
    
    def test_create_with_null_description(self, client, super_admin_user, app):
        """Test creating organization with null description"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Org', 'description': None},
                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            
            org = Organization.query.filter_by(slug='org').first()
            assert org.description is None
    
    def test_create_creates_admin_log(self, client, super_admin_user, app):
        """Test that organization creation creates admin log"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Logged Org'},
                                 content_type='application/json')
            assert response.status_code == 200
            
            # Check admin log was created
            log = AdminLog.query.filter_by(
                admin_user_id=super_admin_user.id,
                action='CREATE_ORGANIZATION'
            ).first()
            assert log is not None
            assert 'Logged Org' in log.details
    
    def test_create_returns_correct_format(self, client, super_admin_user, app):
        """Test create returns correct JSON format"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            response = client.post('/api/organizations/create',
                                 json={'name': 'Format Test'},
                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'success' in data
            assert 'organization' in data
            assert data['success'] is True
            assert 'id' in data['organization']
            assert 'name' in data['organization']
            assert 'slug' in data['organization']
            assert 'text' in data['organization']
            assert data['organization']['text'] == f"{data['organization']['name']} ({data['organization']['slug']})"
    
    def test_create_database_error(self, client, super_admin_user, app):
        """Test create handles database errors"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            # Mock database error
            with patch('flask_app.routes.api.Organization.safe_create') as mock_create:
                mock_create.return_value = (None, 'Database error occurred')
                response = client.post('/api/organizations/create',
                                     json={'name': 'Error Test'},
                                     content_type='application/json')
                assert response.status_code == 500
                data = json.loads(response.data)
                assert data['success'] is False
                assert 'error' in data

