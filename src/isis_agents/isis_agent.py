import math, random, os, Image
from time import time

import direct.directbase.DirectStart 
from direct.showbase.DirectObject import DirectObject 
from direct.actor.Actor import Actor 
from direct.task import Task 

from direct.controls.ControlManager import CollisionHandlerRayStart
from pandac.PandaModules import CollisionTraverser 
from pandac.PandaModules import ActorNode

from direct.showbase import DirectObject
from direct.interval.IntervalGlobal import *
from direct.actor.Actor import Actor
from direct.gui.DirectGui import DirectLabel

from pandac.PandaModules import *# PandaNode,NodePath,Camera

from direct.interval.IntervalGlobal import *

import platform
# project stuff
from ..actions.actions import *
from ..physics.ode.kcc import kinematicCharacterController
from ..physics.ode.odeWorldManager import *
from ..utils import frange


class IsisAgent(kinematicCharacterController,DirectObject):
    
    @classmethod
    def setPhysics(cls,physics):
        """ This method is set in src.loader when the generators are loaded
        into the namespace.  This frees the environment definitions (in 
        scenario files) from having to pass around the physics parameter 
        that is required for all IsisObjects """
        cls.physics = physics


    def __init__(self, name, queueSize = 100):

        # load the model and the different animations for the model into an Actor object.
        self.actor= Actor("media/models/boxman",
                          {"walk":"media/models/boxman-walk", 
                           "idle": "media/models/boxman-idle"})
        self.actor.setScale(1.0)
        self.actor.setH(0)

        self.actor.setColorScale(random.random(), random.random(), random.random(), 1.0)
        self.actorNode = ActorNode('physicsControler-%s' % name)
        self.actorNodePath = NodePath('agent-%s' % name)
        self.actorNodePath.attachNewNode(self.actorNode)
        self.activeModel = self.actorNodePath
        
        self.actorNodePath.reparentTo(render)

        self.actor.reparentTo(self.actorNodePath)
        self.name = name
        self.isMoving = False
        
        kinematicCharacterController.__init__(self, IsisAgent.physics, self.actorNodePath)
        self.setGeomPos(self.actorNodePath.getPos(render))
        """
        Additional Direct Object that I use for convenience.
        """
        self.specialDirectObject = DirectObject()

        """
        Set one of two main variants of handling object carrying.
        See placeObjectInFrontOfCamera method to see what this is for.
        """
        self.jiggleHeld = True

        """
        How high above the center of the capsule you want the camera to be
        when walking and when crouching. It's related to the values in KCC.
        """
        self.walkCamH = 0.7
        self.crouchCamH = 0.2
        self.camH = self.walkCamH

        """
        This tells the Player Controller what we're aiming at.
        """
        self.aimed = None

        self.isSitting = False
        self.isDisabled = False

        """
        The special direct object is used for trigger messages and the like.
        """
        #self.specialDirectObject.accept("ladder_trigger_enter", self.setFly, [True])
        #self.specialDirectObject.accept("ladder_trigger_exit", self.setFly, [False])

    
        self.actor.makeSubpart("arms", ["LeftShoulder", "RightShoulder"])    
        
        # Expose agent's right hand joint to attach objects to
        self.player_right_hand = self.actor.exposeJoint(None, 'modelRoot', 'Hand.R')
        self.player_left_hand  = self.actor.exposeJoint(None, 'modelRoot', 'Hand.L')

        self.right_hand_holding_object = None
        self.left_hand_holding_object  = None

        # don't change the color of things you pick up
        self.player_right_hand.setColorScaleOff()
        self.player_left_hand.setColorScaleOff()
        
        self.player_head  = self.actor.exposeJoint(None, 'modelRoot', 'Head')
        self.neck = self.actor.controlJoint(None, 'modelRoot', 'Head')

        self.controlMap = {"turn_left":0,
                           "turn_right":0,
                           "move_forward":0,
                           "move_backward":0,
                           "move_right":0, 
                           "move_left":0,
                           "look_up":0,
                           "look_down":0,
                           "look_left":0,
                           "look_right":0,
                           "jump":0}
        # see update method for uses, indices are [turn left, turn right, move_forward, move_back, move_right, move_left, look_up, look_down, look_right, look_left]
        # turns are in degrees per second, moves are in units per second
        self.speeds = [270, 270, 5, 5, 5, 5, 60, 60, 60, 60]

        self.originalPos = self.actor.getPos()

 

        # speech bubble
        self.last_spoke = 0
        self.speech_bubble = DirectLabel(parent=self.actor, text="", text_wordwrap=10, pad=(3,3),\
                       relief=None, text_scale=(.3,.3), pos = (0,0,3.6), frameColor=(.6,.2,.1,.5),\
                       textMayChange=1, text_frame=(0,0,0,1), text_bg=(1,1,1,1))
        # stop the speech bubble from being colored like the agent
        self.speech_bubble.setColorScaleOff()
        self.speech_bubble.component('text0').textNode.setCardDecal(1)
        self.speech_bubble.setBillboardAxis()
        # hide the speech bubble from IsisAgent's own camera
        self.speech_bubble.hide(BitMask32.bit(1))
        
        # put a camera on ralph
        self.fov = NodePath(Camera('RaphViz'))
        self.fov.node().setCameraMask(BitMask32.bit(1))
        
        # position the camera to be infront of Boxman's face.
        self.fov.reparentTo(self.player_head)
        # x,y,z are not in standard orientation when parented to player-Head
        self.fov.setPos(0, 0.2, 0)
        # if P=0, canrea is looking directly up. 90 is back of head. -90 is on face.
        self.fov.setHpr(0,-90,0)

        lens = self.fov.node().getLens()
        lens.setFov(60) #  degree field of view (expanded from 40)
        lens.setNear(0.2)
        #self.fov.node().showFrustum() # displays a box around his head
        #self.fov.place()
 
        self.prevtime = 0
        self.current_frame_count = 0

        #self.name = "IsisAgent"
        self.isSitting = False
        self.isDisabled = False
        self.msg = None
        self.actorNodePath.setPythonTag("agent", self)


        # Initialize the action queue, with a maximum length of queueSize
        self.queue = []
        self.queueSize = queueSize
        self.lastSense = 0
        
    def setLayout(self,layout):
        """ Dummy method called by spatial methods for use with objects. 
        Doesn't make sense for an agent that can move around."""
        pass

    def setPos(self,pos):
        """ Wrapper to set the position of the ODE geometry, which in turn 
        sets the visual model's geometry the next time the update() method
        is called. """
        self.setGeomPos(pos)
    
    def setPosition(self,pos):
        self.setPos(pos)
         
    def reparentTo(self, parent):
        self.actorNodePath.reparentTo(parent)

    def setControl(self, control, value):
        """Set the state of one of the character's movement controls.  """
        self.controlMap[control] = value
    
    def get_objects_in_field_of_vision(self,exclude=[]):
        """ This works in an x-ray style. Fast. Works best if you listen to
        http://en.wikipedia.org/wiki/Rock_Art_and_the_X-Ray_Style while
        you use it."""
        objects = {}
        for obj in base.render.findAllMatches("**/IsisObject*"):
            if not obj.hasPythonTag("isisobj"):
                continue
            o = obj.getPythonTag("isisobj")
            bounds = o.activeModel.getBounds() 
            bounds.xform(o.activeModel.getMat(self.fov))
            if self.fov.node().isInView(o.activeModel.getPos(self.fov)):
                pos = o.activeModel.getPos(render)
                pos = (pos[0], pos[1], pos[2]+o.getHeight()/2)
                p1 = self.fov.getRelativePoint(render,pos)
                p2 = Point2()
                self.fov.node().getLens().project(p1, p2)
                p3 = aspect2d.getRelativePoint(render2d, Point3(p2[0], 0, p2[1]) )
                object_dict = {}
                if 'x_pos' not in exclude: object_dict['x_pos'] = p3[0]
                if 'y_pos' not in exclude: object_dict['y_pos'] = p3[2]
                if 'distance' not in exclude: object_dict['distance'] = o.activeModel.getDistance(self.fov)
                if 'orientation' not in exclude: object_dict['orientation'] = o.activeModel.getH(self.fov)
                if 'actions' not in exclude: object_dict['actions'] = o.list_actions()
                if 'isisobject' not in exclude: object_dict['isisobject'] = o
                # add item to dinctionary
                objects[o] = object_dict
        return objects

    def get_agents_in_field_of_vision(self):
        """ This works in an x-ray vision style as well"""
        agents = {}
        for agent in base.render.findAllMatches("**/agent-*"):
            if not agent.hasPythonTag("agent"):
                continue
            a = agent.getPythonTag("agent")
            bounds = a.actorNodePath.getBounds()
            bounds.xform(a.actorNodePath.getMat(self.fov))
            pos = a.actorNodePath.getPos(self.fov)
            if self.fov.node().isInView(pos):
                p1 = self.fov.getRelativePoint(render,pos)
                p2 = Point2()
                self.fov.node().getLens().project(p1, p2)
                p3 = aspect2d.getRelativePoint(render2d, Point3(p2[0], 0, p2[1]))
                agentDict = {'x_pos': p3[0],\
                             'y_pos': p3[2],\
                             'distance':a.actorNodePath.getDistance(self.fov),\
                             'orientation': a.actorNodePath.getH(self.fov)}
                agents[a] = agentDict
        return agents

    def in_view(self,isisobj):
        """ Returns true iff a particular isisobject is in view """
        return len(filter(lambda x: x['isisobject'] == isisobj, self.get_objects_in_field_of_vision().values()))

    def get_objects_in_view(self):
        """ Gets objects through ray tracing.  Slow"""
        return self.picker.get_objects_in_view()
            
    def control__turn_left__start(self, speed=None):
        self.setControl("turn_left",  1)
        self.setControl("turn_right", 0)
        if speed:
            self.speeds[0] = speed
        return "success"

    def control__turn_left__stop(self):
        self.setControl("turn_left",  0)
        return "success"

    def control__turn_right__start(self, speed=None):
        self.setControl("turn_left",  0)
        self.setControl("turn_right", 1)
        if speed:
            self.speeds[1] = speed
        return "success"

    def control__turn_right__stop(self):
        self.setControl("turn_right", 0)
        return "success"

    def control__move_forward__start(self, speed=None):
        self.setControl("move_forward",  1)
        self.setControl("move_backward", 0)
        if speed:
            self.speeds[2] = speed
        return "success"

    def control__move_forward__stop(self):
        self.setControl("move_forward",  0)
        return "success"

    def control__move_backward__start(self, speed=None):
        self.setControl("move_forward",  0)
        self.setControl("move_backward", 1)
        if speed:
            self.speeds[3] = speed
        return "success"

    def control__move_backward__stop(self):
        self.setControl("move_backward", 0)
        return "success"

    def control__move_left__start(self, speed=None):
        self.setControl("move_left",  1)
        self.setControl("move_right", 0)
        if speed:
            self.speeds[4] = speed
        return "success"

    def control__move_left__stop(self):
        self.setControl("move_left",  0)
        return "success"

    def control__move_right__start(self, speed=None):
        self.setControl("move_right",  1)
        self.setControl("move_left", 0)
        if speed:
            self.speeds[5] = speed
        return "success"

    def control__move_right__stop(self):
        self.setControl("move_right",  0)
        return "success"

    def control__look_left__start(self, speed=None):
        self.setControl("look_left",  1)
        self.setControl("look_right", 0)
        if speed:
            self.speeds[9] = speed
        return "success"

    def control__look_left__stop(self):
        self.setControl("look_left",  0)
        return "success"

    def control__look_right__start(self, speed=None):
        self.setControl("look_right",  1)
        self.setControl("look_left", 0)
        if speed:
            self.speeds[8] = speed
        return "success"

    def control__look_right__stop(self):
        self.setControl("look_right",  0)
        return "success"

    def control__look_up__start(self, speed=None):
        self.setControl("look_up",  1)
        self.setControl("look_down", 0)
        if speed:
            self.speeds[6] = speed
        return "success"

    def control__look_up__stop(self):
        self.setControl("look_up",  0)
        return "success"

    def control__look_down__start(self, speed=None):
        self.setControl("look_down",  1)
        self.setControl("look_up",  0)
        if speed:
            self.speeds[7] = speed
        return "success"

    def control__look_down__stop(self):
        self.setControl("look_down",  0)
        return "success"

    def control__jump(self):
        self.setControl("jump",  1)
        return "success"

    def control__view_objects(self):
        """ calls a raytrace to to all objects in view """
        objects = self.get_objects_in_field_of_vision()
        self.control__say("If I were wearing x-ray glasses, I could see %i items"  % len(objects)) 
        print "Objects in view:", objects
        return objects

    def control__sense(self):
        """ perceives the world, returns percepts dict """
        percepts = dict()
        # eyes: visual matricies
        #percepts['vision'] = self.sense__get_vision()
        # objects in purview (cheating object recognition)
        percepts['objects'] = self.sense__get_objects()
        # global position in environment - our robots can have GPS :)
        percepts['position'] = self.sense__get_position()
        # language: get last utterances that were typed
        percepts['language'] = self.sense__get_utterances()
        # agents: returns a map of agents to a list of actions that have been sensed
        percepts['agents'] = self.sense__get_agents()
        print percepts
        return percepts
 
    def control__say_goal(self, message = "Hello!"):
        self.speech_bubble['text'] = "GOAL: "+message
        self.last_spoke = 0
        return "success"

    def control__say(self, message = "Hello!"):
        self.speech_bubble['text'] = message
        self.last_spoke = 0
        return "success"
    
    """

    Methods explicitly for IsisScenario files 

    """

    def put_in_front_of(self,isisobj):
        # find open direction
        pos = isisobj.getGeomPos()
        direction = render.getRelativeVector(isisobj, Vec3(0, 1.0, 0))
        closestEntry, closestObject = IsisAgent.physics.doRaycastNew('aimRay', 5, [pos, direction], [isisobj.geom])   
        print "CLOSEST",closestEntry, closestObject
        if closestObject == None:
            self.setPosition(pos + Vec3(0,2,0))
        else:
            print "CANNOT PLACE IN FRONT OF %s BECAUSE %s IS THERE" % (isisobj,closestObject)
            direction = render.getRelativeVector(isisobj, Vec3(0, -1.0, 0))
            closestEntry, closestObject = IsisAgent.physics.doRaycastNew('aimRay', 5, [pos, direction], [isisobj.geom])     
            if closestEntry == None:
                self.setPosition(pos + Vec3(0,-2,0))
            else:
                print "CANNOT PLACE BEHIND %s BECAUSE %s IS THERE" % (isisobj,closestObject)
                direction = render.getRelativeVector(isisobj, Vec3(1, 0, 0))
                closestEntry, closestObject = IsisAgent.physics.doRaycastNew('aimRay', 5, [pos, direction], [isisobj.geom])    
                if closestEntry == None:
                    self.setPosition(pos + Vec3(2,0,0))
                else:
                    print "CANNOT PLACE TO LEFT OF %s BECAUSE %s IS THERE" % (isisobj,closestObject)
                    # there's only one option left, do it anyway
                    self.setPosition(pos + Vec3(-2,0,0))
        # rotate agent to look at it
        self.actorNodePath.setPos(self.getGeomPos())
        self.actorNodePath.lookAt(pos)
        self.setH(self.actorNodePath.getH())
        
    def put_in_right_hand(self,target):
        return self.pick_object_up_with(target, self.right_hand_holding_object, self.player_right_hand)
                    
    def put_in_left_hand(self,target):
        return self.pick_object_up_with(target, self.left_hand_holding_object, self.player_left_hand)

    def __get_object_in_center_of_view(self):
       direction = render.getRelativeVector(self.fov, Vec3(0, 1.0, 0))
       pos = self.fov.getPos(render)
       exclude = []#[base.render.find("**/kitchenNode*").getPythonTag("isisobj").geom]
       closestEntry, closestObject = IsisAgent.physics.doRaycastNew('aimRay', 5, [pos, direction], exclude)
       return closestObject
    
    def pick_object_up_with(self,target,hand_slot,hand_joint):
        """ Attaches an IsisObject, target, to the hand joint.  Does not check anything first,
        other than the fact that the hand joint is not currently holding something else."""
        if hand_slot != None:
            print 'already holding ' + hand_slot.getName() + '.'
            return None  
        else:
            if target.layout:
                target.layout.remove(target)
                target.layout = None
            # store original position
            target.originalHpr = target.getHpr(render)
            target.disable() #turn off physics
            if target.body: target.body.setGravityMode(0)
            target.reparentTo(hand_joint)
            target.setPosition(hand_joint.getPos(render))
            target.setTag('heldBy', self.name)
            if hand_joint == self.player_right_hand:
                self.right_hand_holding_object = target
            elif hand_joint == self.player_left_hand:
                self.left_hand_holding_object = target
            hand_slot = target
            return target

    def control__pick_up_with_right_hand(self, target=None):
        if not target:
            target = self.__get_object_in_center_of_view()
            if not target:
                print "no target in reach"
                return "error: no target in reach"
        else:
            target = render.find("**/*" + target + "*").getPythonTag("isisobj")    
        print "attempting to pick up " + target.name + " with right hand.\n"
        if self.can_grasp(target): # object within distance      
            return self.pick_object_up_with(target, self.right_hand_holding_object, self.player_right_hand)
        else:
            print 'object (' + target.name + ') is not graspable (i.e. in view and close enough).'
            return 'error: object not graspable'
            
    def control__pick_up_with_left_hand(self, target = None):
        if not target:
            target = self.__get_object_in_center_of_view()
            if not target:
                print "no target in reach"
                return
        else:
            target = render.find("**/*" + target + "*").getPythonTag("isisobj")    
        print "attempting to pick up " + target.name + " with left hand.\n"
        if self.can_grasp(target): # object within distance      
            return  self.pick_object_up_with(target, self.left_hand_holding_object, self.player_left_hand)
        else:
            print 'object (' + target.name + ') is not graspable (i.e. in view and close enough).'
            return 'error: object not graspable'

    def control__drop_from_right_hand(self):
        print "attempting to drop object from right hand.\n"
        
        if self.right_hand_holding_object is None:
            print 'right hand is not holding an object.'
            return False
        if self.right_hand_holding_object.getNetTag('heldBy') == self.name:
            self.right_hand_holding_object.reparentTo(render)
            direction = render.getRelativeVector(self.fov, Vec3(0, 1.0, 0))
            pos = self.player_right_hand.getPos(render)
            heldPos = self.right_hand_holding_object.geom.getPosition()
            self.right_hand_holding_object.setPosition(pos)
            self.right_hand_holding_object.synchPosQuatToNode()
            self.right_hand_holding_object.setTag('heldBy', '')
            self.right_hand_holding_object.setRotation(self.right_hand_holding_object.originalHpr)
            self.right_hand_holding_object.enable()
            if self.right_hand_holding_object.body:
                quat = self.getQuat()
                # throw object
                force = 5
                self.right_hand_holding_object.body.setGravityMode(1)
                self.right_hand_holding_object.getBody().setForce(quat.xform(Vec3(0, force, 0)))
            self.right_hand_holding_object = None
            return 'success'
        else:
            return "Error: not being held by agent %s" % (self.name)

    
    def control__drop_from_left_hand(self):
        print "attempting to drop object from left hand.\n"
        if self.left_hand_holding_object is None:
            return 'left hand is not holding an object.'
        if self.left_hand_holding_object.getNetTag('heldBy') == self.name:
            self.left_hand_holding_object.reparentTo(render)
            direction = render.getRelativeVector(self.fov, Vec3(0, 1.0, 0))
            pos = self.player_left_hand.getPos(render)
            heldPos = self.left_hand_holding_object.geom.getPosition()
            self.left_hand_holding_object.setPosition(pos)
            self.left_hand_holding_object.synchPosQuatToNode()
            self.left_hand_holding_object.setTag('heldBy', '')
            self.left_hand_holding_object.setRotation(self.left_hand_holding_object.originalHpr)
            self.left_hand_holding_object.enable()
            if self.left_hand_holding_object.body:
                quat = self.getQuat()
                # throw object
                force = 5
                self.left_hand_holding_object.body.setGravityMode(1)
                self.left_hand_holding_object.getBody().setForce(quat.xform(Vec3(0, force, 0)))
            self.left_hand_holding_object = None
            return 'success'
        else:
            return "Error: not being held by agent %s" % (self.name)


    def control__use_right_hand(self, target = None, action = None):
        # TODO, rename this to use object with 
        if not action:
            if self.msg:
                action = self.msg
            else:
                action = "divide"
        if not target:
            target = self.__get_object_in_center_of_view()
            if not target:
                print "no target in reach"
                return
        else:
            target = render.find("**/*" + target + "*").getPythonTag('isisobj')
        print "Trying to use object", target
        if self.can_grasp(target):
            if(target.call(self, action, self.right_hand_holding_object) or
              (self.right_hand_holding_object and self.right_hand_holding_object.call(self, action, target))):
                return "success"
            return str(action) + " not associated with either target or object"
        return "target not within reach"

    def control__use_left_hand(self, target = None, action = None):
        if not action:
            if self.msg:
                action = self.msg
            else:
                action = "divide"
        if not target:
            target = self.__get_object_in_center_of_view()
            if not target:
                print "no target in reach"
                return
        else:
            target = render.find("**/*" + target + "*").getPythonTag('isisobj')
        if self.can_grasp(target):
            if(target.call(self, action, self.left_hand_holding_object) or
              (self.left_hand_holding_object and self.left_hand_holding_object.call(self, action, target))):
                return "success"
            return str(action) + " not associated with either target or object"
        return "target not within reach"

    def can_grasp(self, isisobject):
        distance = isisobject.activeModel.getDistance(self.fov)
        print "distance = ", distance
        return distance < 5.0

    def is_holding(self, object_name):
        return ((self.left_hand_holding_object and (self.left_hand_holding_object.getPythonTag('isisobj').name  == object_name)) \
             or (self.right_hand_holding_object and (self.right_hand_holding_object.getPythonTag('isisobj').name == object_name)))

    def empty_hand(self):
        if (self.left_hand_holding_object is None):
            return self.player_left_hand
        elif (self.right_hand_holding_object is None):
            return self.player_right_hand
        return False

    def has_empty_hand(self):
        return (self.empty_hand() is not False)

    def control__use_aimed(self):
        """
        Try to use the object that we aim at, by calling its callback method.
        """
        target = self.__get_object_in_center_of_view()
        if target.selectionCallback:
            target.selectionCallback(self, dir)
        return "success"
                    

    def sense__get_position(self):
        x,y,z = self.actorNodePath.getPos()
        h,p,r = self.actorNodePath.getHpr()
        #FIXME
        # neck is not positioned in Blockman nh,np,nr = self.agents[agent_id].actor_neck.getHpr()
        left_hand_obj = "" 
        right_hand_obj = "" 
        if self.left_hand_holding_object:  left_hand_obj = self.left_hand_holding_object.getName()
        if self.right_hand_holding_object: right_hand_obj = self.right_hand_holding_object.getName()
        return {'body_x': x, 'body_y': y, 'body_z': z,'body_h':h,\
                'body_p': p, 'body_r': r,  'in_left_hand': left_hand_obj, 'in_right_hand':right_hand_obj}

    def sense__get_vision(self):
        self.fov.node().saveScreenshot("temp.jpg")
        image = Image.open("temp.jpg")
        os.remove("temp.jpg")
        return image

    def sense__get_objects(self):
        return dict([x.getName(),y] for (x,y) in self.get_objects_in_field_of_vision().items())

    def sense__get_agents(self):
        curSense = time()
        agents = {}
        for k, v in self.get_agents_in_field_of_vision().items():
            v['actions'] = k.get_other_agents_actions(self.lastSense, curSense)
            agents[k.name] = v
        self.lastSense = curSense
        return agents

    def sense__get_utterances(self):
        """ Clear out the buffer of things that the teacher has typed,
        FIXME: this doesn't work right now """
        return []
        utterances = self.teacher_utterances
        self.teacher_utterances = []
        return utterances

    def debug__print_objects(self):
        text = "Objects in FOV: "+ ", ".join(self.sense__get_objects().keys())
        print text

    def add_action_to_history(self, action, args, result = 0):
        self.queue.append((time(), action, args, result))
        if len(self.queue) > self.queueSize:
            self.queue.pop(0)

    def get_other_agents_actions(self, start = 0, end = None):
        if not end:
            end = time()
        actions = []
        for act in self.queue:
            if act[0] >= start:
                if act[0] < end:
                    actions.append(act)
                else:
                    break
        return actions



    def update(self, stepSize=0.1):
        self.speed = [0.0, 0.0]
        self.actorNodePath.setPos(self.geom.getPosition()+Vec3(0,0,-0.70))
        self.actorNodePath.setQuat(self.getQuat())
        # the values in self.speeds are used as coefficientes for turns and movements
        if (self.controlMap["turn_left"]!=0):        self.addToH(stepSize*self.speeds[0])
        if (self.controlMap["turn_right"]!=0):       self.addToH(-stepSize*self.speeds[1])
        if self.verticalState == 'ground':
            # these actions require contact with the ground
            if (self.controlMap["move_forward"]!=0):     self.speed[1] =  self.speeds[2]
            if (self.controlMap["move_backward"]!=0):    self.speed[1] = -self.speeds[3]
            if (self.controlMap["move_left"]!=0):        self.speed[0] = -self.speeds[4]
            if (self.controlMap["move_right"]!=0):       self.speed[0] =  self.speeds[5]
            if (self.controlMap["jump"]!=0):             
                kinematicCharacterController.jump(self)
                # one jump at a time!
                self.controlMap["jump"] = 0
        if (self.controlMap["look_left"]!=0):        self.neck.setR(bound(self.neck.getR(),-60,60)+stepSize*80)
        if (self.controlMap["look_right"]!=0):       self.neck.setR(bound(self.neck.getR(),-60,60)-stepSize*80)
        if (self.controlMap["look_up"]!=0):          self.neck.setP(bound(self.neck.getP(),-60,80)+stepSize*80)
        if (self.controlMap["look_down"]!=0):        self.neck.setP(bound(self.neck.getP(),-60,80)-stepSize*80)

        kinematicCharacterController.update(self, stepSize)

        """
        Update the held object position to be in the hands
        """
        if self.right_hand_holding_object != None:
            self.right_hand_holding_object.setPosition(self.player_right_hand.getPos(render))
        if self.left_hand_holding_object != None:
            self.left_hand_holding_object.setPosition(self.player_left_hand.getPos(render))

        """ 
        Update the dialog box.
        This allows dialogue window to gradually decay (changing transparancy) and then disappear
        """
        self.last_spoke += stepSize/2
        self.speech_bubble['text_bg']=(1,1,1,1/(self.last_spoke+0.01))
        self.speech_bubble['frameColor']=(.6,.2,.1,.5/(self.last_spoke+0.01))
        if self.last_spoke > 2:
            self.speech_bubble['text'] = ""

        # If the character is moving, loop the run animation.
        # If he is standing still, stop the animation.
        if (self.controlMap["move_forward"]!=0) or (self.controlMap["move_backward"]!=0) or (self.controlMap["move_left"]!=0) or (self.controlMap["move_right"]!=0):
            if self.isMoving is False:
                self.isMoving = True
        else:
            if self.isMoving:
                self.current_frame_count = 5.0
                self.isMoving = False

        total_frame_num = self.actor.getNumFrames('walk')
        if self.isMoving:
            self.current_frame_count = self.current_frame_count + (stepSize*250.0)
            if self.current_frame_count > total_frame_num:
                self.current_frame_count = self.current_frame_count%total_frame_num
            self.actor.pose('walk', self.current_frame_count)
        elif self.current_frame_count != 0:
            self.current_frame_count = 0
            self.actor.pose('idle', 0)
        return Task.cont
        
    def destroy(self):
        self.disable()
        self.specialDirectObject.ignoreAll()
        self.actorNodePath.removeNode()
        del self.specialDirectObject

        kinematicCharacterController.destroy(self)

    def disable(self):
        self.isDisabled = True
        self.geom.disable()
        self.footRay.disable()

    def enable(self):
        self.footRay.enable()
        self.geom.enable()
        self.isDisabled = False
    """
    Set camera to correct height above the center of the capsule
    when crouching and when standing up.
    """
    def crouch(self):
        kinematicCharacterController.crouch(self)
        self.camH = self.crouchCamH

    def crouchStop(self):
        """
        Only change the camera's placement when the KCC allows standing up.
        See the KCC to find out why it might not allow it.
        """
        if kinematicCharacterController.crouchStop(self):
            self.camH = self.walkCamH

    """
    This method is used when carrying objects around.
    """
    def placeObjectInFrontOfCamera(self, object, curve = None):
        """
        Whether to disable the geom's collisions when carrying an object or not.
        """
        disable = False

        """
        Whether to curve the geom's movement when carrying an object or not.
        That is, whether to place the object directly in front of the camera, or
        move it just up and down on one axis relative to the capsule.

        The way I use this is as follows:

        For objects like boxes or balls, that they player can carry around and stack I disable curveUp.
        This makes it easier to stack boxes for example.

        For objects like granades, which are meant to be thrown, I enable curveUp.
        This allows the object to be thrown from the center of the camera when
        looking up.

        NOTE that there's no curve down. That's because it would make the player stand
        on the carried object.
        """
        if curve is None:
            if hasattr(object,'pickableType'):
                curveUp = False
                disable = False
            else:
                curveUp = True
                disable = True

        geom = object.geom
        body = object.body

        if disable:
            geom.disable()
            if body:
                body.disable()

        camQuat = self.fov.getQuat()
        capsuleQuat = self.geom.getQuaternion()

        """
        Dividing this allows me to control how high the object goes when looking up.
        Experiment with this value.
        """
        z = camQuat.getHpr()[1]/30
        if z < -1.3:
            z = -1.3

        if curveUp:
            zoffset = 0.7
        else:
            zoffset = 0.3

        """
        Get the current position of the geom for manipulating.
        """
        currentPos = self.geom.getPosition()

        """
        Place the geom relative to the capsule or relative to the camera depending
        on curveUp and z value.
        """
        if curveUp and z >= 0.0:
            newPos = currentPos + camQuat.xform(Vec3(0.0, 1.3 + (0.35 * z), zoffset - (0.2 * z)))
        else:
            newPos = currentPos + capsuleQuat.xform(Vec3(0.0, 1.3, zoffset + z))


        """
        This is the "jiggling" mechanics. When the object is kept enabled, this controlls
        whether and how the other objects and the static environment affect the held object.

        If jiggling is enabled, you will notice that the held item reacts to collisions with
        other objects. Note however that it doesn't prevent the held object from penetrating
        other objects, so it might look a little strange.

        I wrote it because it looks funny. You can compare it to the Wobbly windows in Compiz.
        """
        if self.jiggleHeld and body and body.getLinearVel().length() > 0.0:
            newPos += body.getLinearVel() * self.map.worldManager.stepSize * 4.0

        geom.setPosition(newPos)
        geom.setQuaternion(capsuleQuat)

        """
        Make sure to disable the gravity for the held object's body
        """
        if body:
            body.setGravityMode(0)
            body.setPosition(newPos)
            body.setQuaternion(capsuleQuat)




def map3dToAspect2d(node, point):
    """Maps the indicated 3-d point (a Point3), which is relative to 
    the indicated NodePath, to the corresponding point in the aspect2d 
    scene graph. Returns the corresponding Point3 in aspect2d. 
    Returns None if the point is not onscreen. """ 
    # Convert the point to the 3-d space of the camera 
    p3 = self.fov.getRelativePoint(node, point) 

    # Convert it through the lens to render2d coordinates 
    p2 = Point2()
    if not self.fov.node().getLens().project(p3, p2):
        return None 
    r2d = Point3(p2[0], 0, p2[1])
    # And then convert it to aspect2d coordinates 
    a2d = aspect2d.getRelativePoint(render2d, r2d)
    return a2d


