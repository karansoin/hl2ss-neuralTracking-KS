# add paths for external python libraries
extLibs = ['../viewer', 'venv/Lib/site-packages']
for extLib in extLibs:
	if extLib not in sys.path:
		sys.path = extLibs + sys.path

import numpy as np
import select
from collections import deque
import hl2ss
import hl2ss_lnm
import hl2ss_3dcv
import hl2ss_mp
import json

class Hl2ssExt:
	"""
	Wrapper around hl2ss python library - allowing its usage within TD.
	"""
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.data = None
		self.calibration = None
		
		self.client = None
		self.buffer = deque(maxlen = self.ownerComp.par.Bufferlen.eval())
		self.framestamp = 0
		self.lastPresentedFramestamp = 0

		# multiprocessing
		self.producer = hl2ss_mp.producer()
		self.sink = None

		# initial cleanup
		op('metadata').text = op('default_metadata').text
		self.ownerComp.par.Stream = False

	def __delTD__(self):
		"""Triggered before extension is destroyed. Perform cleanup.
		"""
		self.CloseStream()

	@property
	def Data(self):
		"""Access original hl2ss data.
		"""
		return self.data
	
	@property
	def Calibration(self):
		"""Access original hl2ss calibration.
		"""
		return self.calibration
	
	@property
	def port(self):
		return int(self.ownerComp.par.Port.eval())
	
	@property
	def threadMode(self):
		return self.ownerComp.par.Threadmode.eval()
	
	def getPVFormat(self):
		format = self.ownerComp.par.Format.eval()
		resolution = format.split('@')[0].split('x')
		width = int(resolution[0])
		height = int(resolution[1])
		framerate = int(format.split('@')[1])
		return width, height, framerate
	
	def getClient(self):
		# HoloLens address
		host = self.ownerComp.par.Address.eval()

		# Operating mode
		# 0: video
		# 1: video + rig pose
		# 2: query calibration (single transfer)
		mode = hl2ss.StreamMode.MODE_1

		# Framerate denominator (must be > 0)
		# Effective framerate is framerate / divisor
		divisor = 1

		# Video encoding profile
		profile = int( self.ownerComp.par.Videoprofile.eval() )

		# PV | Enable Mixed Reality Capture (Holograms)
		enableMrc = self.ownerComp.par.Enablemrc.eval()

		# PV | Enable Shared Capture
		# If another program is already using the PV camera, you can still stream it by
		# enabling shared mode, however you cannot change the resolution and framerate
		shared = self.ownerComp.par.Shared.eval()

		# PV | camera parameters
		# Ignored in shared mode
		width, height, framerate = self.getPVFormat()

		# PV | Decoded format
		decodedFormat = self.ownerComp.par.Colorformat.eval()

		if self.port in (
			hl2ss.StreamPort.RM_VLC_LEFTFRONT,
			hl2ss.StreamPort.RM_VLC_LEFTLEFT,
			hl2ss.StreamPort.RM_VLC_RIGHTFRONT,
			hl2ss.StreamPort.RM_VLC_RIGHTRIGHT
			):
			client = hl2ss_lnm.rx_rm_vlc(host, self.port, mode=mode, divisor=divisor, profile=profile)
		
		elif self.port == hl2ss.StreamPort.RM_DEPTH_AHAT:
			client = hl2ss_lnm.rx_rm_depth_ahat(host, self.port, mode=mode, divisor=divisor, profile_z=hl2ss.DepthProfile.SAME, profile_ab=profile)
		
		elif self.port == hl2ss.StreamPort.RM_DEPTH_LONGTHROW:
			client = hl2ss_lnm.rx_rm_depth_longthrow(host, self.port, mode=mode, divisor=divisor)

		elif self.port in (
			hl2ss.StreamPort.RM_IMU_ACCELEROMETER,
			hl2ss.StreamPort.RM_IMU_GYROSCOPE,
			hl2ss.StreamPort.RM_IMU_MAGNETOMETER
			):
			client = hl2ss_lnm.rx_rm_imu(host, self.port, mode=mode)
			
		elif self.port == hl2ss.StreamPort.PERSONAL_VIDEO:
			hl2ss_lnm.start_subsystem_pv(host, self.port, enable_mrc=enableMrc, shared=shared)
			client = hl2ss_lnm.rx_pv(host, self.port, mode=mode, width=width, height=height, framerate=framerate, divisor=divisor, profile=profile, decoded_format=decodedFormat)
		
		return client
	
	def GetCalibration(self):
		host = self.ownerComp.par.Address.eval()
		calibFolder = self.ownerComp.par.Calibfolder.evalFile().path

		# store calibration for any downstream python-based cv
		if self.port == hl2ss.StreamPort.PERSONAL_VIDEO:
			width, height, framerate = self.getPVFormat()
			hl2ss_lnm.start_subsystem_pv(host, self.port, enable_mrc=self.ownerComp.par.Enablemrc.eval(), shared=self.ownerComp.par.Shared.eval())
			# focus is set to 0 as it doesn't seem to be used in hl2ss_3dcv
			self.calibration = hl2ss_3dcv.get_calibration_pv(host, self.port, calibFolder, 0, width, height, framerate)
			hl2ss_lnm.stop_subsystem_pv(host, self.port)
		else:
			self.calibration = hl2ss_3dcv.get_calibration_rm(host, self.port, calibFolder)

	def OpenStream(self):
		match self.threadMode:
			case 'sync':
				if self.client is None:
					if self.ownerComp.par.Autogetcalib:
						self.GetCalibration()
					self.buffer = deque(maxlen = self.ownerComp.par.Bufferlen.eval())
					self.framestamp = 0
					self.lastPresentedFramestamp = 0
					self.client = self.getClient()
					try:
						self.client.open()
						self.ownerComp.color = (0.05, 0.5, 0.2)
						self.ownerComp.clearScriptErrors(recurse=False, error="Can't connect to HL.")
					except:
						self.client = None
						self.ownerComp.par.Stream = False
						self.ownerComp.addScriptError("Can't connect to HL.")
				else:
					debug('Stream is already open.')
			
			case 'mp':
				if self.sink is None:
					if self.ownerComp.par.Autogetcalib:
						self.GetCalibration()
					self.lastPresentedFramestamp = 0
					client = self.getClient()
					
					manager = self.ownerComp.par.Mpmanager.eval().Manager
					consumer = hl2ss_mp.consumer()
					self.producer.configure( self.port, client )
					self.producer.initialize( self.port, self.ownerComp.par.Bufferlen.eval() )
					self.producer.start( self.port )
					self.sink = consumer.create_sink(self.producer, self.port, manager, None)
					self.sink.get_attach_response()
					while (self.sink.get_buffered_frame(0)[0] != 0):
						pass
					self.ownerComp.color = (0.35, 0.5, 0.05)
				else:
					debug('Stream is already open.')

	def CloseStream(self):
		match self.threadMode:
			case 'sync':
				if self.client is not None:
					self.client.close()
					self.client = None
				else:
					debug('Stream is already closed.')
			
			case 'mp':
				if self.sink is not None:
					self.sink.detach()
					self.sink = None
					self.producer.stop(self.port)
				else:
					debug('Stream is already closed.')

		self.ownerComp.par.Stream = False
		self.ownerComp.color = (0.55, 0.55, 0.55)

		# cleanup PV
		if self.port == hl2ss.StreamPort.PERSONAL_VIDEO:
			hl2ss_lnm.stop_subsystem_pv(self.ownerComp.par.Address.eval(), self.port)

	def OnTdFrame(self) -> bool:
		"""Try to receive new data and process next frame.
		This method needs to run on each TD frame.

		Returns:
		    bool: Success of providing new data.
		"""
		if self.threadMode == 'sync' and self.client is not None:
			self.recvData(self.client)

		return self.GetAndPresentFrame(extObj=self)
			
	def recvData(self, client):
		"""Try to receive data from client using "semi-non-blocking" approach.
		Semi-non-blocking means it won't wait (and block) if first chunk of next
		packet isn't available. However if first chunk is available, it will
		block until full packet (all chunks) is received. Since chunks usually
		arrive closely thogether, this kinda works without slowing TD down.
		"""
		while self.socketSelect(client):
			data = client.get_next_packet()
			self.buffer.append(data)
			self.framestamp += 1
	
	def socketSelect(self, client) -> bool:
		"""Check if client's socket has some data available (non-blocking).
		"""
		# get underling socket of client
		# rx_rm_vlc._client -> _gatherer._client -> _client._socket
		socket = client._client._client._socket
		
		# instead of blocking with recv, check if sockets has available data
		# toRead will be a list of sockets with readable data
		toRead, toWrite, errors = select.select([socket], [], [], 0)
		return len(toRead) > 0
	
	def GetAndPresentFrame(self, extObj) -> bool:
		"""Pick next frame (if available) and store it for downstream
		processing.

		Args:
		    extObj: Specifies which extension object will be used for frame
		    picker settings and final data storage. Its purpose is to enable
		    decoupled frame picker fuctionality.

		Returns:
		    bool: Success of providing new data.
		"""
		if self.threadMode == 'sync' and (self.client is None or len(self.buffer) == 0):
			return False
		elif self.threadMode == 'mp' and self.sink is None:
			return False

		pickerMode = extObj.ownerComp.par.Framepicker.eval()
		refMetadata = extObj.ownerComp.op('json_ref_metadata')
		fs, data = self.getFrame(pickerMode, refMetadata)

		if data is not None and fs > extObj.lastPresentedFramestamp:
			# store data for any downstream python-based cv
			extObj.data = data
			# present data to TD
			self.handleData(fs, data, targetComp=extObj.ownerComp)
			extObj.lastPresentedFramestamp = fs
			return True
		return False
	
	def getFrame(self, pickerMode: str, refMetadata: DAT):
		match pickerMode:
			case 'getLatestFrame':
				return self.getLatestFrame()
			case 'getNearestFrame':
				targetTimestamp = int(refMetadata.source['timestamp'])
				return self.getNearestFrame(targetTimestamp)
			case 'getBufferedFrame':
				targetFramestamp = int(refMetadata.source['framestamp'])
				return self.getBufferedFrame(targetFramestamp)
			case _:
				return (None, None)

	def getLatestFrame(self):
		match self.threadMode:
			case 'sync':
				return (self.framestamp, self.buffer[-1])
			case 'mp':
				return self.sink.get_most_recent_frame()
	
	def getNearestFrame(self, timestamp):
		match self.threadMode:
			case 'sync':
				index = hl2ss_mp._get_nearest_packet(self.buffer, timestamp)
				return (None, None) if (index is None) else (self.framestamp - len(self.buffer) + 1 + index, self.buffer[index])
			case 'mp':
				return self.sink.get_nearest(timestamp)
	
	def getBufferedFrame(self, framestamp):
		match self.threadMode:
			case 'sync':
				n = len(self.buffer)
				index = n - 1 - self.framestamp + framestamp
				return (-1, None) if (index < 0) else (1, None) if (index >= n) else (framestamp, self.buffer[index])
			case 'mp':
				state, data = self.sink.get_buffered_frame(framestamp)
				return (framestamp, data) if state == 0 else (state, data)
	
	def handleData(self, framestamp: int, data: hl2ss._packet, targetComp: COMP = None):
		"""Push hl2ss data to TD.
		"""
		if targetComp == None:
			targetComp = self.ownerComp

		if self.port in (
			hl2ss.StreamPort.RM_VLC_LEFTFRONT,
			hl2ss.StreamPort.RM_VLC_LEFTLEFT,
			hl2ss.StreamPort.RM_VLC_RIGHTFRONT,
			hl2ss.StreamPort.RM_VLC_RIGHTRIGHT
			):
			self.processImage(data.payload, targetComp.op('script_img1'))
			metadata = {
				'framestamp': framestamp,
				'timestamp': data.timestamp,
				'pose': data.pose.ravel().tolist()
			}

		elif self.port == hl2ss.StreamPort.RM_DEPTH_AHAT or self.port == hl2ss.StreamPort.RM_DEPTH_LONGTHROW:
			self.processImage(data.payload.depth, targetComp.op('script_img1'))
			self.processImage(data.payload.ab, targetComp.op('script_img2'))
			metadata = {
				'framestamp': framestamp,
				'timestamp': data.timestamp,
				'pose': data.pose.ravel().tolist()
			}

		elif self.port in (
			hl2ss.StreamPort.RM_IMU_ACCELEROMETER,
			hl2ss.StreamPort.RM_IMU_GYROSCOPE,
			hl2ss.StreamPort.RM_IMU_MAGNETOMETER
			):
			self.processImu(data.payload, targetComp.op('script_chop'))
			metadata = {
				'framestamp': framestamp,
				'timestamp': data.timestamp,
				'pose': data.pose.ravel().tolist()
			}

		elif self.port == hl2ss.StreamPort.PERSONAL_VIDEO:
			self.processImage(data.payload.image, targetComp.op('script_img1'))
			metadata = {
				'framestamp': framestamp,
				'timestamp': data.timestamp,
				'pose': data.pose.ravel().tolist(),
				'focal_length': data.payload.focal_length.tolist(),
				'principal_point': data.payload.principal_point.tolist()
			}

		targetComp.op('metadata').text = json.dumps(metadata, indent=4)

	def processImage(self, img, scriptOp):
		"""Push image into Script TOP.
		"""
		if img.ndim == 2:
			# contains mono image, needs 3rd dimension (single channel) for each value
			img = np.expand_dims(img, 2)
		scriptOp.lock = True
		scriptOp.copyNumpyArray(img)
		scriptOp.lock = False

	def processImu(self, payload, scriptOp):
		"""Push IMU data into Script CHOP.
		vinyl_hup_ticks and soc_ticks are skipped (won't fit into floats).
		"""
		imuData = hl2ss.unpack_rm_imu(payload)
		count = imuData.get_count()
		chopData = np.zeros((4, count), dtype=np.float32)
		for i in range(count):
			sample = imuData.get_frame(i)
			chopData[0, i] = sample.x
			chopData[1, i] = sample.y
			chopData[2, i] = sample.z
			chopData[3, i] = sample.temperature
		scriptOp.lock = True
		scriptOp.copyNumpyArray(chopData, baseName='chan')
		scriptOp.lock = False

	# def metadata2Chop(self, data, constChop):
	# 	constChop.seq.const.numBlocks = 17
	# 	# write timestamp
	# 	constChop.seq.const[0].par.name = 'timestamp'
	# 	constChop.seq.const[0].par.value = data.timestamp
	# 	# write pose matrix
	# 	mtxNames = ['m00', 'm10', 'm20', 'm30', 'm01', 'm11', 'm21', 'm31', 'm02', 'm12', 'm22', 'm32', 'm03', 'm13', 'm23', 'm33']
	# 	pose = np.ravel(data.pose)
	# 	for i in range(16):
	# 		constChop.seq.const[i + 1].par.name = mtxNames[i]
	# 		constChop.seq.const[i + 1].par.value = pose[i]

	def GetFlipFlops(self) -> tuple[bool, bool, int]:
		"""Provides correct image transformation
		(based on currect port) for Flip TOP.

		Returns:
			Tuple containing FlipX, FlipY, Flop.
		"""
		if self.port == hl2ss.StreamPort.RM_VLC_LEFTFRONT:
			return (False, False, 2)
		elif self.port == hl2ss.StreamPort.RM_VLC_LEFTLEFT:
			return (False, False, 1)
		elif self.port == hl2ss.StreamPort.RM_VLC_RIGHTFRONT:
			return (False, False, 1)
		elif self.port == hl2ss.StreamPort.RM_VLC_RIGHTRIGHT:
			return (False, False, 2)
		elif self.port == hl2ss.StreamPort.RM_DEPTH_AHAT or self.port == hl2ss.StreamPort.RM_DEPTH_LONGTHROW:
			return (False, True, 0)
		elif self.port == hl2ss.StreamPort.PERSONAL_VIDEO:
			return (False, True, 0)
		else:
			return (False, False, 0)
		
	def GetChopNames(self) -> str:
		"""Provides correct channel names for Rename CHOP.
		"""
		if self.port in (
			hl2ss.StreamPort.RM_IMU_ACCELEROMETER,
			hl2ss.StreamPort.RM_IMU_GYROSCOPE,
			hl2ss.StreamPort.RM_IMU_MAGNETOMETER
			):
			return 'x y z temperature'
		else:
			return ''