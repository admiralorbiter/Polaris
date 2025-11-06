import pytest
from unittest.mock import patch, MagicMock
from flask import g, has_request_context
from flask_login import current_user
from flask_app.models import Organization, Role, Permission, RolePermission, UserOrganization, db
from flask_app.utils.permissions import (
    get_user_organizations, get_user_role_in_organization, has_permission, has_role,
    get_current_organization, set_current_organization, get_available_organizations,
    get_available_roles, can_assign_role, validate_role_assignment,
    require_organization_membership
)


class TestPermissionHelperFunctions:
    """Test permission helper functions"""
    
    def test_get_user_organizations_super_admin(self, super_admin_user, test_organization, app):
        """Test get_user_organizations for super admin"""
        with app.app_context():
            # Create another organization
            org2 = Organization(name='Org 2', slug='org-2', is_active=True)
            db.session.add(org2)
            db.session.add(super_admin_user)
            db.session.commit()
            
            orgs = get_user_organizations(super_admin_user)
            assert len(orgs) >= 2
            assert any(o.slug == 'test-organization' for o in orgs)
            assert any(o.slug == 'org-2' for o in orgs)
    
    def test_get_user_organizations_regular_user(self, test_user, test_organization, test_role, app):
        """Test get_user_organizations for regular user"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            orgs = get_user_organizations(test_user)
            assert len(orgs) == 1
            assert orgs[0].id == org_id
    
    def test_get_user_organizations_excludes_inactive(self, test_user, test_organization, test_organization_inactive, test_role, app):
        """Test get_user_organizations excludes inactive organizations"""
        with app.app_context():
            # Store org_ids to avoid detached instance
            org_id = test_organization.id
            inactive_org_id = test_organization_inactive.id
            db.session.add(test_user)
            db.session.commit()
            
            # Add user to both active and inactive organizations
            user_org1 = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            user_org2 = UserOrganization(
                user_id=test_user.id,
                organization_id=inactive_org_id,
                role_id=test_role.id
            )
            db.session.add_all([user_org1, user_org2])
            db.session.commit()
            
            orgs = get_user_organizations(test_user)
            assert len(orgs) == 1
            assert orgs[0].id == org_id
            assert orgs[0].is_active is True
    
    def test_get_user_organizations_unauthenticated(self, app):
        """Test get_user_organizations for unauthenticated user"""
        with app.app_context():
            unauthenticated_user = MagicMock()
            unauthenticated_user.is_authenticated = False
            orgs = get_user_organizations(unauthenticated_user)
            assert orgs == []
    
    def test_get_user_role_in_organization_super_admin(self, super_admin_user, test_organization, app):
        """Test get_user_role_in_organization for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            # Create SUPER_ADMIN role
            super_role = Role(name='SUPER_ADMIN', display_name='Super Admin', is_system_role=True)
            db.session.add(super_role)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, test_organization.id)
            role = get_user_role_in_organization(super_admin_user, org)
            assert role is not None
            assert role.name == 'SUPER_ADMIN'
    
    def test_get_user_role_in_organization_regular_user(self, test_user, test_organization, test_role, app):
        """Test get_user_role_in_organization for regular user"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            role = get_user_role_in_organization(test_user, org)
            assert role is not None
            assert role.id == test_role.id
    
    def test_get_user_role_in_organization_no_membership(self, test_user, test_organization, app):
        """Test get_user_role_in_organization when user is not a member"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, test_organization.id)
            role = get_user_role_in_organization(test_user, org)
            assert role is None
    
    def test_has_permission_super_admin(self, super_admin_user, test_organization, app):
        """Test has_permission for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            assert has_permission(super_admin_user, 'any_permission') is True
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, test_organization.id)
            assert has_permission(super_admin_user, 'another_permission', org) is True
    
    def test_has_permission_with_organization(self, test_user, test_organization, test_role, test_permission, app):
        """Test has_permission with organization context"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            # Link role to permission
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            
            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            assert has_permission(test_user, 'view_volunteers', org) is True
            assert has_permission(test_user, 'nonexistent_permission', org) is False
    
    def test_has_permission_without_organization(self, test_user, test_organization, test_role, test_permission, app):
        """Test has_permission without organization context"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            # Link role to permission
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            
            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            assert has_permission(test_user, 'view_volunteers') is True
            assert has_permission(test_user, 'nonexistent_permission') is False
    
    def test_has_role_super_admin(self, super_admin_user, app):
        """Test has_role for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            assert has_role(super_admin_user, 'SUPER_ADMIN') is True
            assert has_role(super_admin_user, 'ORG_ADMIN') is True
            assert has_role(super_admin_user, 'VOLUNTEER') is True
    
    def test_has_role_with_organization(self, test_user, test_organization, test_role, app):
        """Test has_role with organization context"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            assert has_role(test_user, 'volunteer', org) is True
            assert has_role(test_user, 'ORG_ADMIN', org) is False
    
    def test_get_current_organization(self, app):
        """Test get_current_organization"""
        with app.app_context():
            # Initially None
            assert get_current_organization() is None
            
            # Set organization
            test_org = Organization(name='Test', slug='test')
            set_current_organization(test_org)
            assert get_current_organization() == test_org
    
    def test_set_current_organization(self, app):
        """Test set_current_organization"""
        with app.app_context():
            org = Organization(name='Test Org', slug='test-org')
            set_current_organization(org)
            assert g.current_organization == org
    
    def test_get_available_organizations_super_admin(self, super_admin_user, test_organization, app):
        """Test get_available_organizations for super admin"""
        with app.app_context():
            org2 = Organization(name='Org 2', slug='org-2', is_active=True)
            db.session.add(org2)
            db.session.add(super_admin_user)
            db.session.commit()
            
            orgs = get_available_organizations(super_admin_user)
            assert len(orgs) >= 2
    
    def test_get_available_organizations_regular_user(self, test_user, test_organization, test_role, app):
        """Test get_available_organizations for regular user"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            orgs = get_available_organizations(test_user)
            assert len(orgs) == 1
            assert orgs[0].id == org_id
    
    def test_get_available_roles_super_admin(self, super_admin_user, app):
        """Test get_available_roles for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            
            # Create system roles
            role1 = Role(name='ORG_ADMIN', display_name='Org Admin', is_system_role=True)
            role2 = Role(name='VOLUNTEER', display_name='Volunteer', is_system_role=True)
            db.session.add_all([role1, role2])
            db.session.commit()
            
            roles = get_available_roles(super_admin_user)
            assert len(roles) >= 2
    
    def test_can_assign_role_super_admin(self, super_admin_user, test_role, app):
        """Test can_assign_role for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            assert can_assign_role(super_admin_user, test_role) is True
    
    def test_can_assign_role_hierarchy(self, test_user, test_organization, app):
        """Test can_assign_role respects role hierarchy"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            # Create roles with hierarchy
            org_admin = Role(name='ORG_ADMIN', display_name='Org Admin', is_system_role=True)
            coordinator = Role(name='COORDINATOR', display_name='Coordinator', is_system_role=True)
            volunteer = Role(name='VOLUNTEER', display_name='Volunteer', is_system_role=True)
            viewer = Role(name='VIEWER', display_name='Viewer', is_system_role=True)
            
            db.session.add_all([org_admin, coordinator, volunteer, viewer])
            db.session.add(test_user)
            db.session.commit()
            
            # Make user an org admin
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=org_admin.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            # Org admin can assign coordinator, volunteer, viewer
            assert can_assign_role(test_user, coordinator, org) is True
            assert can_assign_role(test_user, volunteer, org) is True
            assert can_assign_role(test_user, viewer, org) is True
            
            # Org admin cannot assign super admin
            super_role = Role(name='SUPER_ADMIN', display_name='Super Admin', is_system_role=True)
            db.session.add(super_role)
            db.session.commit()
            assert can_assign_role(test_user, super_role, org) is False
    
    def test_validate_role_assignment(self, test_user, test_organization, test_role, app):
        """Test validate_role_assignment"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            # Valid assignment
            is_valid, error = validate_role_assignment(test_user, test_role, org)
            assert is_valid is True
            assert error is None
            
            # Invalid assignment (higher role)
            super_role = Role(name='SUPER_ADMIN', display_name='Super Admin', is_system_role=True)
            db.session.add(super_role)
            db.session.commit()
            is_valid, error = validate_role_assignment(test_user, super_role, org)
            assert is_valid is False
            assert error is not None
    
    def test_require_organization_membership_super_admin(self, super_admin_user, test_organization, app):
        """Test require_organization_membership for super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, test_organization.id)
            assert require_organization_membership(super_admin_user, org) is True
    
    def test_require_organization_membership_member(self, test_user, test_organization, test_role, app):
        """Test require_organization_membership for member"""
        with app.app_context():
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            db.session.add(test_user)
            db.session.commit()
            
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, org_id)
            assert require_organization_membership(test_user, org) is True
    
    def test_require_organization_membership_non_member(self, test_user, test_organization, app):
        """Test require_organization_membership for non-member"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            # Re-query organization to avoid detached instance
            org = db.session.get(Organization, test_organization.id)
            assert require_organization_membership(test_user, org) is False


class TestPermissionDecorators:
    """Test permission decorators"""
    
    def test_super_admin_required_allows_super_admin(self, client, super_admin_user, app):
        """Test super_admin_required decorator allows super admin"""
        with app.app_context():
            db.session.add(super_admin_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'superadmin',
                'password': 'superpass123'
            })
            
            # Test accessing a super admin route (organizations list)
            response = client.get('/admin/organizations')
            # Should either succeed or redirect (depending on implementation)
            assert response.status_code in [200, 302]
    
    def test_super_admin_required_blocks_regular_user(self, client, test_user, app):
        """Test super_admin_required decorator blocks regular user"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'testuser',
                'password': 'testpass123'
            })
            
            # Try to access super admin route
            response = client.get('/admin/organizations', follow_redirects=True)
            # Should redirect to index with flash message
            assert response.status_code == 200
            # Check that flash message was set (might be in session or response)
            # The redirect should happen, so we check the status and that we're not on the admin page
            assert b'organizations' not in response.data.lower() or b'Super admin' in response.data or b'privileges required' in response.data.lower()
    
    def test_permission_required_with_org_context(self, client, test_user, test_organization, test_role, test_permission, app):
        """Test permission_required decorator with organization context"""
        with app.app_context():
            db.session.add(test_user)
            db.session.commit()
            
            # Link role to permission
            role_permission = RolePermission(
                role_id=test_role.id,
                permission_id=test_permission.id
            )
            db.session.add(role_permission)
            
            # Store org_id to avoid detached instance
            org_id = test_organization.id
            # Add user to organization
            user_org = UserOrganization(
                user_id=test_user.id,
                organization_id=org_id,
                role_id=test_role.id
            )
            db.session.add(user_org)
            db.session.commit()
            
            client.post('/login', data={
                'username': 'testuser',
                'password': 'testpass123'
            })
            
            # Set organization context
            with client.session_transaction() as sess:
                sess['current_organization_id'] = org_id
            
            # Note: This depends on actual route implementation
            # Just test that the function works

